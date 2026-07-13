"""External API endpoints authenticated via API keys.

These endpoints mirror a subset of the internal REST API but use API key
authentication instead of JWT cookies. They are intended for programmatic
access by third-party integrations and automation scripts.
"""
from __future__ import annotations

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from urllib.parse import quote

from app.api.v1.auth import get_current_api_key_user, require_api_scope
from app.api.v1.chat import _blocked_response, _retrieve_and_generate
from app.api.v1.search import _build_search_response, _persist_search_history
from app.core.exceptions import NotFoundException, PermissionDeniedException
from app.database import get_db
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.schemas.chat import ChatRequest, ChatResponse
from app.schemas.document import DocumentLinkCreate, DocumentListResponse, DocumentResponse
from app.schemas.knowledge_base import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseStats,
    KnowledgeBaseUpdate,
)
from app.schemas.search import SearchRequest, SearchResponse
from app.schemas.user import UserResponse
from app.services.conversation_service import conversation_service
from app.services.document_service import DocumentService
from app.services.security_gateway import security_gateway
from app.workers.ingest_tasks import process_document

router = APIRouter(prefix="/external", tags=["External API"])


def _require_kb_access(kb: KnowledgeBase, current_user: UserResponse) -> None:
    """Ownership check reused from the internal KB router."""
    if kb.owner_id and str(kb.owner_id) != str(current_user.id):
        raise PermissionDeniedException("没有权限访问该知识库")


async def _get_kb(db: AsyncSession, kb_id: UUID) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise NotFoundException(f"知识库 {kb_id} 不存在")
    return kb


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #


@router.post(
    "/search",
    response_model=SearchResponse,
    dependencies=[Depends(require_api_scope("search"))],
)
async def external_search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Hybrid search across knowledge bases (scope: ``search``)."""
    from app.services.retrieval_service import retrieval_service

    results = await retrieval_service.search(
        db=db,
        user_id=current_user.id,
        query=request.query,
        kb_ids=request.kb_ids,
        modalities=request.modalities,
        top_k=request.top_k,
        rerank_top_k=request.rerank_top_k,
        mode=request.mode,
    )
    await _persist_search_history(db, current_user.id, request, len(results))
    return _build_search_response(request, results)


@router.post(
    "/search/semantic",
    response_model=SearchResponse,
    dependencies=[Depends(require_api_scope("search"))],
)
async def external_semantic_search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Semantic-only search (scope: ``search``)."""
    from app.services.retrieval_service import retrieval_service

    results = await retrieval_service.semantic_search(
        db=db,
        user_id=current_user.id,
        query=request.query,
        kb_ids=request.kb_ids,
        modalities=request.modalities,
        top_k=request.top_k,
        rerank_top_k=request.rerank_top_k,
    )
    await _persist_search_history(db, current_user.id, request, len(results))
    return _build_search_response(request, results)


@router.post(
    "/search/keyword",
    response_model=SearchResponse,
    dependencies=[Depends(require_api_scope("search"))],
)
async def external_keyword_search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """BM25 keyword search (scope: ``search``)."""
    from app.services.retrieval_service import retrieval_service

    results = await retrieval_service.keyword_search(
        db=db,
        user_id=current_user.id,
        query=request.query,
        kb_ids=request.kb_ids,
        modalities=request.modalities,
        top_k=request.top_k,
        rerank_top_k=request.rerank_top_k,
    )
    await _persist_search_history(db, current_user.id, request, len(results))
    return _build_search_response(request, results)


# --------------------------------------------------------------------------- #
# Chat
# --------------------------------------------------------------------------- #


@router.post(
    "/chat",
    response_model=ChatResponse,
    dependencies=[Depends(require_api_scope("chat"))],
)
async def external_chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Non-streaming RAG chat (scope: ``chat``)."""
    if security_gateway.detect_prompt_injection(request.query):
        return _blocked_response(request)

    if request.stream:
        return await external_chat_stream(request, db, current_user)

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
        sources=result.get("sources", []),
        strategy=result.get("strategy"),
        conversation_id=conversation_id,
    )


@router.post(
    "/chat/stream",
    dependencies=[Depends(require_api_scope("chat"))],
)
async def external_chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Streaming RAG chat (scope: ``chat``)."""
    from sse_starlette.sse import EventSourceResponse

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
        history = await conversation_service.build_history_messages(
            db=db,
            conversation_id=conversation_id,
            user_id=current_user.id,
        )

    async def event_generator():
        if security_gateway.detect_prompt_injection(request.query):
            yield {"data": "检测到提示注入攻击，请求已被拦截。"}
            return

        fast_strategy = await security_gateway._fast_level_check(
            db, current_user.id, request.query
        )
        if fast_strategy and fast_strategy["strategy"] == "local_only":
            yield {"data": "当前查询涉及绝密内容，禁止调用外部API生成回答。"}
            return

        from app.services.retrieval_service import retrieval_service

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

        from app.services.compression_service import compression_service
        from app.services.generation_service import generation_service

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


# --------------------------------------------------------------------------- #
# Knowledge base management
# --------------------------------------------------------------------------- #


@router.post(
    "/knowledge-bases",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_scope("kb:write"))],
)
async def external_create_knowledge_base(
    payload: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Create a new knowledge base (scope: ``kb:write``)."""
    kb = KnowledgeBase(
        name=payload.name,
        description=payload.description,
        config=payload.config,
        owner_id=current_user.id,
    )
    db.add(kb)
    await db.commit()
    await db.refresh(kb)
    return kb


@router.get(
    "/knowledge-bases",
    response_model=list[KnowledgeBaseResponse],
    dependencies=[Depends(require_api_scope("kb:read"))],
)
async def external_list_knowledge_bases(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """List accessible knowledge bases (scope: ``kb:read``)."""
    stmt = (
        select(KnowledgeBase)
        .where(KnowledgeBase.owner_id == current_user.id)
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/knowledge-bases/{kb_id}",
    response_model=KnowledgeBaseResponse,
    dependencies=[Depends(require_api_scope("kb:read"))],
)
async def external_get_knowledge_base(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Get a knowledge base (scope: ``kb:read``)."""
    kb = await _get_kb(db, kb_id)
    _require_kb_access(kb, current_user)
    return kb


@router.patch(
    "/knowledge-bases/{kb_id}",
    response_model=KnowledgeBaseResponse,
    dependencies=[Depends(require_api_scope("kb:write"))],
)
async def external_update_knowledge_base(
    kb_id: UUID,
    payload: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Update a knowledge base (scope: ``kb:write``)."""
    kb = await _get_kb(db, kb_id)
    _require_kb_access(kb, current_user)

    if payload.name is not None:
        kb.name = payload.name
    if payload.description is not None:
        kb.description = payload.description
    if payload.config is not None:
        kb.config = payload.config
    if payload.status is not None:
        kb.status = payload.status

    await db.commit()
    await db.refresh(kb)
    return kb


@router.delete(
    "/knowledge-bases/{kb_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_scope("kb:write"))],
)
async def external_delete_knowledge_base(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Delete a knowledge base (scope: ``kb:write``)."""
    kb = await _get_kb(db, kb_id)
    _require_kb_access(kb, current_user)
    await db.delete(kb)
    await db.commit()
    return None


@router.get(
    "/knowledge-bases/{kb_id}/stats",
    response_model=KnowledgeBaseStats,
    dependencies=[Depends(require_api_scope("kb:read"))],
)
async def external_get_knowledge_base_stats(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Knowledge base statistics (scope: ``kb:read``)."""
    kb = await _get_kb(db, kb_id)
    _require_kb_access(kb, current_user)

    kb_id_str = str(kb_id)
    doc_count_result = await db.execute(
        select(func.count(Document.id)).where(Document.kb_id == kb_id_str)
    )
    document_count = doc_count_result.scalar() or 0

    status_result = await db.execute(
        select(Document.status, func.count(Document.id))
        .where(Document.kb_id == kb_id_str)
        .group_by(Document.status)
    )
    status_breakdown = {status: count for status, count in status_result.all()}

    from app.models.chunk import Chunk

    chunk_count_result = await db.execute(
        select(func.count(Chunk.id)).where(
            Chunk.doc_id.in_(select(Document.id).where(Document.kb_id == kb_id_str))
        )
    )
    chunk_count = chunk_count_result.scalar() or 0

    last_upload_result = await db.execute(
        select(func.max(Document.created_at)).where(Document.kb_id == kb_id_str)
    )
    last_upload_at = last_upload_result.scalar()

    return KnowledgeBaseStats(
        kb_id=kb_id,
        document_count=document_count,
        chunk_count=chunk_count,
        status_breakdown=status_breakdown,
        last_upload_at=last_upload_at,
    )


# --------------------------------------------------------------------------- #
# Documents
# --------------------------------------------------------------------------- #


async def _require_document_access(
    db: AsyncSession,
    current_user: UserResponse,
    doc_id: UUID,
) -> DocumentResponse:
    """Verify access to a document through its knowledge base."""
    service = DocumentService(db)
    doc = await service.get_document(doc_id)
    kb = await _get_kb(db, doc.kb_id)
    _require_kb_access(kb, current_user)
    return doc


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    response_model=DocumentListResponse,
    dependencies=[Depends(require_api_scope("kb:read"))],
)
async def external_list_documents(
    kb_id: UUID,
    status: str | None = None,
    skip: int = 0,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """List documents in a knowledge base (scope: ``kb:read``)."""
    kb = await _get_kb(db, kb_id)
    _require_kb_access(kb, current_user)
    service = DocumentService(db)
    total, items = await service.list_documents(kb_id, status, skip, limit)
    return DocumentListResponse(total=total, items=list(items))


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_scope("doc:write"))],
)
async def external_upload_document(
    kb_id: UUID,
    file: UploadFile = File(...),
    tags: str | None = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Upload a document to a knowledge base (scope: ``doc:write``)."""
    kb = await _get_kb(db, kb_id)
    _require_kb_access(kb, current_user)

    file_bytes = await file.read()
    metadata = {"tags": tags.split(",") if tags else []}
    service = DocumentService(db)
    doc = await service.upload_document(
        kb_id=kb_id,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
        created_by=current_user.id,
        metadata=metadata,
    )
    process_document.delay(str(doc.id))
    return doc


@router.post(
    "/knowledge-bases/{kb_id}/documents/link",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_api_scope("doc:write"))],
)
async def external_create_link_document(
    kb_id: UUID,
    link_data: DocumentLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Create a link document (scope: ``doc:write``)."""
    kb = await _get_kb(db, kb_id)
    _require_kb_access(kb, current_user)

    service = DocumentService(db)
    doc = await service.create_link_document(
        kb_id=kb_id,
        link_data=link_data,
        created_by=current_user.id,
    )
    process_document.delay(str(doc.id))
    return doc


@router.get(
    "/documents/{doc_id}",
    response_model=DocumentResponse,
    dependencies=[Depends(require_api_scope("kb:read"))],
)
async def external_get_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Get document details (scope: ``kb:read``)."""
    try:
        return await _require_document_access(db, current_user, doc_id)
    except NotFoundException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")


@router.get(
    "/documents/{doc_id}/download",
    dependencies=[Depends(require_api_scope("kb:read"))],
)
async def external_download_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Download document raw file (scope: ``kb:read``)."""
    await _require_document_access(db, current_user, doc_id)
    service = DocumentService(db)
    try:
        body, media_type, filename, redirect_url = await service.get_file_stream(doc_id)
    except NotFoundException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if redirect_url:
        return RedirectResponse(url=redirect_url)

    encoded = quote(filename)
    return StreamingResponse(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{encoded}"},
    )


@router.get(
    "/documents/{doc_id}/preview",
    dependencies=[Depends(require_api_scope("kb:read"))],
)
async def external_preview_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Preview document raw file inline (scope: ``kb:read``)."""
    await _require_document_access(db, current_user, doc_id)
    service = DocumentService(db)
    try:
        body, media_type, filename, redirect_url = await service.get_file_stream(doc_id)
    except NotFoundException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    if redirect_url:
        return RedirectResponse(url=redirect_url)

    encoded = quote(filename)
    return StreamingResponse(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f"inline; filename*=UTF-8''{encoded}"},
    )


@router.delete(
    "/documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_api_scope("doc:write"))],
)
async def external_delete_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_api_key_user),
):
    """Delete a document (scope: ``doc:write``)."""
    await _require_document_access(db, current_user, doc_id)
    service = DocumentService(db)
    try:
        await service.delete_document(doc_id)
    except NotFoundException:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return None
