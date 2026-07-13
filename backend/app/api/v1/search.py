"""Search / retrieval endpoints."""
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.exceptions import PermissionDeniedException
from app.database import get_db
from app.models.knowledge_base import KnowledgeBase
from app.models.search_history import SearchHistory
from app.schemas.search import (
    SearchHistoryResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)
from app.schemas.user import UserResponse
from app.services.retrieval_service import retrieval_service

router = APIRouter(prefix="/search", tags=["search"])


async def _check_kb_ids_access(
    db: AsyncSession,
    current_user: UserResponse,
    kb_ids: List[UUID],
) -> None:
    """P0-1 修复: 校验用户对所有 kb_ids 拥有访问权限（与 chat.py 同步）。"""
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


async def _persist_search_history(
    db: AsyncSession,
    user_id: UUID,
    request: SearchRequest,
    result_count: int,
) -> None:
    """Persist a search query to the user's history (best-effort)."""
    try:
        history = SearchHistory(
            user_id=user_id,
            query=request.query,
            mode=request.mode,
            kb_ids=[str(k) for k in request.kb_ids],
            result_count=result_count,
            metadata_={
                "top_k": request.top_k,
                "rerank_top_k": request.rerank_top_k,
                "modalities": request.modalities,
            },
        )
        db.add(history)
        await db.commit()
    except Exception:
        # Search history is non-critical; rollback and continue.
        await db.rollback()


def _build_search_response(
    request: SearchRequest,
    results: List[dict],
) -> SearchResponse:
    """Build a typed SearchResponse from raw service results."""
    items: List[SearchResultItem] = []
    for r in results:
        items.append(
            SearchResultItem(
                chunk_id=r.get("chunk_id", ""),
                doc_id=r.get("doc_id", ""),
                content=r.get("content", ""),
                modality=r.get("modality", "text"),
                score=(
                    r.get("rerank_score")
                    if r.get("rerank_score") is not None
                    else r.get("score", 0.0)
                ),
                rerank_score=r.get("rerank_score"),
                max_keyword_level=r.get("max_keyword_level", "L0"),
                filtered=r.get("filtered", False),
                position_info=r.get("position_info"),
                tags=r.get("tags"),
            )
        )
    return SearchResponse(
        query=request.query,
        mode=request.mode,
        total=len(items),
        results=items,
    )


@router.post("", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """混合检索（向量 + BM25 + RRF + Cross-Encoder）。"""
    await _check_kb_ids_access(db, current_user, list(request.kb_ids or []))
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


@router.post("/semantic", response_model=SearchResponse)
async def semantic_search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """纯向量检索。"""
    await _check_kb_ids_access(db, current_user, list(request.kb_ids or []))
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


@router.post("/keyword", response_model=SearchResponse)
async def keyword_search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """纯 BM25 关键词检索。"""
    await _check_kb_ids_access(db, current_user, list(request.kb_ids or []))
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


@router.get("/history", response_model=SearchHistoryResponse)
async def search_history(
    limit: int = Query(20, ge=1, le=100),
    mode: str | None = Query(None, pattern="^(hybrid|semantic|keyword)$"),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """返回当前用户的最近搜索历史。"""
    stmt = (
        select(SearchHistory)
        .where(SearchHistory.user_id == current_user.id)
        .order_by(desc(SearchHistory.created_at))
        .limit(limit)
    )
    if mode:
        stmt = stmt.where(SearchHistory.mode == mode)

    result = await db.execute(stmt)
    items = list(result.scalars().all())
    return SearchHistoryResponse(total=len(items), items=items)
