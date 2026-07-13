from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.api.v1.auth import get_current_user
from app.core.exceptions import PermissionDeniedException
from app.database import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationResponse,
    FeedbackCreate,
    MessageResponse,
    SourceItem,
)
from app.schemas.user import UserResponse
from app.services.compression_service import compression_service
from app.services.conversation_service import conversation_service
from app.services.generation_service import generation_service
from app.services.retrieval_service import retrieval_service
from app.services.security_gateway import security_gateway

router = APIRouter(prefix="/chat", tags=["chat"])


async def _check_kb_ids_access(
    db: AsyncSession,
    current_user: UserResponse,
    kb_ids: List[UUID],
) -> None:
    """P0-1 修复: 校验用户对所有 kb_ids 拥有访问权限。

    - admin 账号（settings.ADMIN_USERNAMES）跳过检查
    - 其他用户必须为每个 kb 的 owner
    - 共享/成员权限可通过 PermissionService 后续扩展
    """
    from app.api.v1.auth import is_admin

    if is_admin(current_user):
        return
    if not kb_ids:
        return
    for kb_id in kb_ids:
        kb = await db.get(KnowledgeBase, kb_id)
        if kb is None:
            raise PermissionDeniedException(f"知识库 {kb_id} 不存在或无权访问")
        if kb.owner_id and str(kb.owner_id) != str(current_user.id):
            raise PermissionDeniedException("没有权限访问该知识库")


async def _retrieve_and_generate(
    db: AsyncSession,
    user_id: UUID,
    query: str,
    kb_ids: List[UUID],
    modalities: List[str],
    top_k: int,
    rerank_top_k: int,
    max_context_tokens: int,
    history: List[dict] | None,
    stream: bool,
):
    """统一的检索与生成逻辑。"""
    # Fast pre-retrieval security check for L4 users / L4 queries.
    fast_strategy = await security_gateway._fast_level_check(db, user_id, query)
    if fast_strategy and fast_strategy["strategy"] == "local_only":
        return {
            "answer": "当前查询涉及绝密内容，禁止调用外部API生成回答。",
            "intercepted": True,
            "sources": [],
            "strategy": fast_strategy,
        }

    chunks = await retrieval_service.search(
        db=db,
        user_id=user_id,
        query=query,
        kb_ids=kb_ids,
        modalities=modalities,
        top_k=top_k,
        rerank_top_k=rerank_top_k,
    )

    strategy = await security_gateway.decide_api_strategy(
        db, user_id, chunks, query
    )

    if strategy["strategy"] == "local_only":
        return {
            "answer": "当前查询涉及绝密内容，禁止调用外部API生成回答。",
            "intercepted": True,
            "sources": [],
            "strategy": strategy,
        }

    # 压缩上下文（虽然生成服务也会构建，这里可用于日志/审计）
    compression_service.compress_chunks(
        chunks, max_tokens=max_context_tokens
    )

    result = None
    try:
        result = await generation_service.generate_answer(
            db=db,
            query=query,
            context_chunks=chunks,
            user_id=user_id,
            stream=stream,
            history=history,
        )
    except Exception as e:
        # Graceful degradation: 生成服务失败时，回退到基于检索片段的回答
        fallback_chunks = chunks[:5]
        result = {
            "answer": (
                "抱歉，回答生成服务暂时不可用，以下是检索到的相关片段：\n\n"
                + "\n\n---\n\n".join(
                    (c.get("content", "") or "")[:500] for c in fallback_chunks
                )
            ),
            "intercepted": False,
            "sources": [
                {
                    "doc_id": c.get("doc_id"),
                    "chunk_id": c.get("chunk_id"),
                    "content": (c.get("content", "") or "")[:200],
                    "score": c.get("rerank_score") or c.get("score", 0),
                    "modality": c.get("modality", "text"),
                    "position_info": c.get("position_info") or {},
                }
                for c in chunks
            ],
            "degraded": True,
            "error": str(e),
        }
    result["strategy"] = strategy
    return result


@router.post("/conversations", response_model=ConversationResponse)
async def create_conversation(
    request: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """创建新会话。"""
    conversation = await conversation_service.create_conversation(
        db=db,
        user_id=current_user.id,
        title=request.title or "新会话",
        kb_ids=request.kb_ids,
    )
    return conversation


@router.get("/conversations", response_model=List[ConversationResponse])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """列出当前用户的会话。"""
    conversations = await conversation_service.list_conversations(
        db=db, user_id=current_user.id
    )
    return conversations


@router.get(
    "/conversations/{conversation_id}/messages",
    response_model=List[MessageResponse],
)
async def get_messages(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """获取指定会话的消息列表。"""
    conversation = await conversation_service.get_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        )
    messages = await conversation_service.get_messages(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    return messages


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """删除指定会话及其消息。"""
    deleted = await conversation_service.delete_conversation(
        db=db,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
        )
    return None


def _blocked_response(request: ChatRequest) -> ChatResponse:
    return ChatResponse(
        answer="检测到提示注入攻击，请求已被拦截。",
        intercepted=True,
        sources=[],
        strategy={"strategy": "blocked", "reason": "prompt injection detected"},
        conversation_id=request.conversation_id,
    )


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """非流式问答，支持 conversation_id 多轮对话。"""
    if security_gateway.detect_prompt_injection(request.query):
        return _blocked_response(request)

    if request.stream:
        return await chat_stream(request, db, current_user)

    conversation_id = request.conversation_id
    history = None
    kb_ids = request.kb_ids

    if conversation_id:
        conversation = await conversation_service.get_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
            )
        if request.kb_ids:
            # 更新会话关联的知识库
            conversation.kb_ids = [str(k) for k in request.kb_ids]
            await db.commit()
        else:
            kb_ids = [UUID(k) for k in (conversation.kb_ids or [])]

    # 校验当前用户对所有 kb_ids 的访问权限
    await _check_kb_ids_access(db, current_user, kb_ids)

    if conversation_id:
        history = await conversation_service.build_history_messages(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )

    result = await _retrieve_and_generate(
        db=db,
        user_id=current_user.id,
        query=request.query,
        kb_ids=kb_ids,
        modalities=request.modalities,
        top_k=request.top_k or 10,
        rerank_top_k=request.rerank_top_k or 5,
        max_context_tokens=request.max_context_tokens or 4000,
        history=history,
        stream=False,
    )

    if conversation_id:
        await conversation_service.add_message(
            db=db,
            conversation_id=conversation_id,
            role="user",
            content=request.query,
            sources=[],
        )
        await conversation_service.add_message(
            db=db,
            conversation_id=conversation_id,
            role="assistant",
            content=result["answer"],
            sources=result.get("sources", []),
        )

    return ChatResponse(
        answer=result["answer"],
        intercepted=result["intercepted"],
        sources=[SourceItem(**s) for s in result.get("sources", [])],
        strategy=result.get("strategy"),
        conversation_id=conversation_id,
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """流式问答，支持 conversation_id 多轮对话。"""
    conversation_id = request.conversation_id
    history = None
    kb_ids = request.kb_ids

    if conversation_id:
        conversation = await conversation_service.get_conversation(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )
        if not conversation:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在"
            )
        if request.kb_ids:
            conversation.kb_ids = [str(k) for k in request.kb_ids]
            await db.commit()
        else:
            kb_ids = [UUID(k) for k in (conversation.kb_ids or [])]

    # 校验当前用户对所有 kb_ids 的访问权限
    await _check_kb_ids_access(db, current_user, kb_ids)

    if conversation_id:
        history = await conversation_service.build_history_messages(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )

    async def event_generator():
        if security_gateway.detect_prompt_injection(request.query):
            yield {"data": "检测到提示注入攻击，请求已被拦截。"}
            return

        chunks = await retrieval_service.search(
            db=db,
            user_id=current_user.id,
            query=request.query,
            kb_ids=kb_ids,
            modalities=request.modalities,
            top_k=request.top_k or 10,
            rerank_top_k=request.rerank_top_k or 5,
        )

        strategy = await security_gateway.decide_api_strategy(
            db, current_user.id, chunks, request.query
        )

        if strategy["strategy"] == "local_only":
            yield {"data": "当前查询涉及绝密内容，禁止调用外部API生成回答。"}
            return

        compression_service.compress_chunks(
            chunks, max_tokens=request.max_context_tokens or 4000
        )

        stream_iter = await generation_service.generate_answer(
            db=db,
            query=request.query,
            context_chunks=chunks,
            user_id=current_user.id,
            stream=True,
            history=history,
        )
        full_answer = ""
        async for token in stream_iter:
            full_answer += token
            yield {"data": token}

        # 构造 sources 用于历史溯源
        sources = [
            {
                "doc_id": c.get("doc_id"),
                "chunk_id": c.get("chunk_id"),
                "content": (c.get("content", "") or "")[:200],
                "score": c.get("rerank_score") or c.get("score", 0),
                "modality": c.get("modality", "text"),
                "position_info": c.get("position_info") or {},
            }
            for c in chunks
        ]

        # 流式结束后持久化消息（保留 sources 用于历史溯源）
        if conversation_id:
            await conversation_service.add_message(
                db=db,
                conversation_id=conversation_id,
                role="user",
                content=request.query,
                sources=[],
            )
            await conversation_service.add_message(
                db=db,
                conversation_id=conversation_id,
                role="assistant",
                content=full_answer,
                sources=sources,
            )

    return EventSourceResponse(event_generator())


@router.post("/messages/{message_id}/feedback", response_model=MessageResponse)
async def add_feedback(
    message_id: UUID,
    request: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """为助手消息添加反馈。"""
    message = await conversation_service.update_feedback(
        db=db,
        message_id=message_id,
        user_id=current_user.id,
        rating=request.rating,
        comment=request.comment,
    )
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="消息不存在"
        )
    return message
