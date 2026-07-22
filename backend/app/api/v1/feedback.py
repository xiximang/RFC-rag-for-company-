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

    return {
        "id": fb.id,
        "status": "ok",
    }
