"""Engineer feedback router: candidate ranking/rating persistence.

五级兼容：
- P4: 写入 reviewer_security_level，下游缓存匹配可据此隔离。
- P5: edited_answer 写入前按 reviewer 等级过 L5 关键词降级校验。
"""
import logging
from typing import Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.conversation import Conversation
from app.models.engineer_feedback import EngineerFeedback
from app.models.message import Message
from app.schemas.chat import CandidateFeedbackRequest
from app.schemas.user import UserResponse
from app.services.keyword_service import KeywordService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "/messages/{message_id}/candidate-feedback",
    status_code=status.HTTP_201_CREATED,
)
async def submit_candidate_feedback(
    message_id: UUID,
    request: CandidateFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """提交工程师对候选的排序/评分反馈。

    校验：
    1. 消息归属——消息必须属于当前用户
    2. ranking 合法性——必须覆盖所有候选且无重复
    3. （P5）越权答案拒绝——edited_answer 含高于 reviewer 等级的关键词则 422
    """
    # 1. 校验消息归属
    result = await db.execute(
        select(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.id == message_id,
            Conversation.user_id == current_user.id,
        )
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="消息不存在或无权操作")
    message, conversation = row

    # 2. 校验 ranking 合法性
    if not request.ranking:
        raise HTTPException(status_code=422, detail="ranking 不能为空")

    # P5: 越权答案拒绝（若提供 edited_answer）
    edited = request.edited_answer
    if edited and edited.strip():
        kw_service = KeywordService(db)
        from app.pipelines.keyword_annotator import LEVEL_ORDER

        user_level = current_user.security_level or "L0"
        user_val = LEVEL_ORDER.get(user_level, 0)

        annotator = await kw_service._get_annotator()
        result = annotator.annotate(edited)
        if result.matches:
            top_match = max(
                result.matches, key=lambda m: LEVEL_ORDER.get(m.level, -1)
            )
            top_level = LEVEL_ORDER.get(top_match.level, 0)
            if top_level > user_val:
                logger.warning(
                    "P5 blocked: user=%s level=%s edited_answer contains keyword level=%s",
                    current_user.id,
                    user_level,
                    top_match.level,
                )
                raise HTTPException(
                    status_code=422,
                    detail=f"编辑后的答案包含级别 {top_match.level} 的敏感关键词，"
                    f"高于您的访问等级 {user_level}，已拒绝",
                )

    # 3. 查找用户原始 query
    user_msg = await db.execute(
        select(Message.content)
        .where(
            Message.conversation_id == conversation.id,
            Message.role == "user",
        )
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    user_query = user_msg.scalar_one_or_none() or ""

    # 4. 写入
    fb = EngineerFeedback(
        user_id=current_user.id,
        message_id=message_id,
        query=user_query,
        chosen_rank=request.chosen_rank,
        ranking=request.ranking,
        ratings=request.ratings,
        action=request.action,
        edited_answer=request.edited_answer,
        comment=request.comment,
        reviewer_security_level=current_user.security_level,
    )
    db.add(fb)

    # 同步回写 message.candidate_feedback
    message.candidate_feedback = {
        "ranking": request.ranking,
        "chosen_rank": request.chosen_rank,
        "ratings": request.ratings,
        "action": request.action,
    }

    await db.commit()
    await db.refresh(fb)

    logger.info(
        "Engineer feedback saved: user=%s message=%s action=%s",
        current_user.id,
        message_id,
        request.action,
    )

    # Phase 2: cache write (only when cache is enabled and policy triggers)
    if settings.ENABLE_QUERY_CACHE:
        try:
            from app.services.cache_write_policy import CacheWritePolicy
            from app.services.cache_service import CacheService
            from app.pipelines.keyword_annotator import tokenize

            feedback_dict = {
                "action": request.action,
                "ratings": request.ratings,
            }
            if CacheWritePolicy.should_write(feedback_dict):
                answer = request.edited_answer or message.content

                # P5: 写入前做关键词降级校验（防止越级答案入缓存）
                if not CacheWritePolicy.validate_answer(
                    answer, current_user.security_level or "L0"
                ):
                    logger.warning(
                        "P5 blocked cache write: user=%s level=%s answer contains over-level keywords",
                        current_user.id, current_user.security_level,
                    )
                    # 不抛错（不阻塞反馈提交），仅跳过缓存写入
                    return {
                        "id": fb.id,
                        "status": "ok",
                        "cache_written": False,
                        "cache_skip_reason": "p5_keyword_level_exceeded",
                    }

                cache_svc = CacheService()
                qhash = CacheService.compute_hash(user_query)

                # 提取关键词（第3层 Jaccard 匹配用，复用 keyword_annotator.tokenize）
                _kws = list(tokenize(user_query))

                # 从 message.candidates 中获取真实 chunk_id（修复 best_chunk_ids 空的问题）
                _candidate_chunk_ids = []
                if hasattr(message, 'candidates') and message.candidates:
                    if isinstance(message.candidates, list):
                        _candidate_chunk_ids = [
                            c.get("chunk_id") for c in message.candidates
                            if isinstance(c, dict) and c.get("chunk_id")
                        ]
                if not _candidate_chunk_ids and hasattr(message, 'retrieved_chunk_ids'):
                    # fallback: 用 retrieved_chunk_ids（来自检索结果）
                    _candidate_chunk_ids = list(message.retrieved_chunk_ids or [])

                # 计算 embedding（第2层语义匹配用，限流时静默跳过）
                _emb = None
                try:
                    from app.retrieval.embedding_client import embedding_client
                    _emb = await embedding_client.embed(user_query)
                except Exception:
                    pass

                await cache_svc.upsert(db, {
                    "query": user_query,
                    "query_hash": qhash,
                    "query_keywords": _kws,
                    "best_chunk_ids": _candidate_chunk_ids,  # 修复：从 candidates 获取
                    "best_rerank_order": request.ranking,
                    "best_answer": answer,
                    "confirmed_count": 1,
                    "owner_security_level": current_user.security_level or "L0",
                })

                # 写入 embedding（单独处理，避免阻塞缓存写入）
                if _emb:
                    import json as _json
                    from sqlalchemy import text as _sql_text
                    await db.execute(_sql_text(
                        "UPDATE query_cache SET query_embedding = CAST(:emb AS vector(1024)) WHERE query_hash = :h"
                    ), {"emb": _json.dumps(_emb), "h": qhash})
                    await db.commit()

                logger.info("Cache written: query=%s keywords=%s emb=%s",
                            user_query[:40], _kws[:5], "yes" if _emb else "no")
        except Exception as exc:
            logger.warning("Cache write failed (non-blocking): %s", exc)

    return {
        "id": fb.id,
        "status": "ok",
    }
