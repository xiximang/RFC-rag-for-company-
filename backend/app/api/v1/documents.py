from typing import List, Optional
from urllib.parse import quote
from uuid import UUID
from fastapi import APIRouter, Depends, UploadFile, File, Form, status, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.config import settings
from app.core.exceptions import NotFoundException, PermissionDeniedException, ValidationException
from app.database import get_db
from app.models.knowledge_base import KnowledgeBase
from app.schemas.document import DocumentResponse, DocumentListResponse, DocumentLinkCreate
from app.schemas.user import UserResponse
from app.services.document_service import DocumentService
from app.workers.ingest_tasks import process_document, _process_document_async_safe

router = APIRouter(prefix="/documents", tags=["documents"])


def _dispatch_ingest(doc_id: str, background: BackgroundTasks) -> None:
    """Schedule a document ingest without blocking the request.

    Lightweight mode uses EAGER Celery, which under FastAPI must run as a
    background task on the existing event loop. We use FastAPI's
    BackgroundTasks so the coroutine is scheduled after the response is sent
    but the connection to the client stays available.
    """
    background.add_task(_process_document_async_safe, doc_id)


async def _get_kb(db: AsyncSession, kb_id: UUID) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None:
        raise NotFoundException(f"知识库 {kb_id} 不存在")
    return kb


async def _require_kb_access(
    db: AsyncSession,
    current_user: UserResponse,
    kb_id: UUID,
) -> KnowledgeBase:
    """Verify the current user can access the knowledge base.

    Simple ownership check: the user must be the KB owner. Shared/member access
    can be added via the permission service later.
    """
    kb = await _get_kb(db, kb_id)
    if kb.owner_id and str(kb.owner_id) != str(current_user.id):
        raise PermissionDeniedException("没有权限访问该知识库")
    return kb


async def _require_document_access(
    db: AsyncSession,
    current_user: UserResponse,
    doc_id: UUID,
) -> DocumentResponse:
    """Verify the current user can access the document's knowledge base."""
    service = DocumentService(db)
    doc = await service.get_document(doc_id)
    await _require_kb_access(db, current_user, doc.kb_id)
    return doc

@router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    background: BackgroundTasks,
    kb_id: UUID = Form(...),
    file: UploadFile = File(...),
    tags: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user)
):
    """上传文档到指定知识库"""
    file_bytes = await file.read()
    metadata = {"tags": tags.split(",") if tags else []}

    await _require_kb_access(db, current_user, kb_id)

    service = DocumentService(db)
    doc = await service.upload_document(
        kb_id=kb_id,
        filename=file.filename,
        content_type=file.content_type or "application/octet-stream",
        file_bytes=file_bytes,
        created_by=current_user.id,
        metadata=metadata
    )

    # 异步触发摄取任务（不阻塞 HTTP 响应）
    _dispatch_ingest(str(doc.id), background)
    return doc

@router.post("/link", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def create_link_document(
    background: BackgroundTasks,
    kb_id: UUID,
    link_data: DocumentLinkCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user)
):
    """创建链接文档"""
    await _require_kb_access(db, current_user, kb_id)

    service = DocumentService(db)
    doc = await service.create_link_document(
        kb_id=kb_id,
        link_data=link_data,
        created_by=current_user.id
    )
    _dispatch_ingest(str(doc.id), background)
    return doc

@router.get("/{kb_id}", response_model=DocumentListResponse)
async def list_documents(
    kb_id: UUID,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user)
):
    """列出知识库下的文档（需要访问权限）"""
    await _require_kb_access(db, current_user, kb_id)
    service = DocumentService(db)
    total, items = await service.list_documents(kb_id, status, skip, limit)
    return DocumentListResponse(total=total, items=list(items))

@router.get("/detail/{doc_id}", response_model=DocumentResponse)
async def get_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user)
):
    """获取文档详情"""
    try:
        return await _require_document_access(db, current_user, doc_id)
    except NotFoundException:
        raise HTTPException(status_code=404, detail="Document not found")


@router.get("/detail/{doc_id}/download")
async def download_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """下载文档原始文件（需要访问权限）"""
    await _require_document_access(db, current_user, doc_id)
    service = DocumentService(db)
    try:
        body, media_type, filename, redirect_url = await service.get_file_stream(doc_id)
    except NotFoundException:
        raise HTTPException(status_code=404, detail="Document not found")

    if redirect_url:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=redirect_url)

    encoded = quote(filename)
    return StreamingResponse(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded}",
        },
    )


@router.get("/detail/{doc_id}/preview")
async def preview_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """在线预览文档原始文件（浏览器支持的格式直接展示，需要访问权限）"""
    await _require_document_access(db, current_user, doc_id)
    service = DocumentService(db)
    try:
        body, media_type, filename, redirect_url = await service.get_file_stream(doc_id)
    except NotFoundException:
        raise HTTPException(status_code=404, detail="Document not found")

    if redirect_url:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=redirect_url)

    encoded = quote(filename)
    return StreamingResponse(
        body,
        media_type=media_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{encoded}",
        },
    )


@router.delete("/detail/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user)
):
    """删除文档"""
    service = DocumentService(db)
    try:
        await _require_document_access(db, current_user, doc_id)
        await service.delete_document(doc_id)
    except NotFoundException:
        raise HTTPException(status_code=404, detail="Document not found")
    return None


@router.post("/{doc_id}/reprocess", response_model=DocumentResponse)
async def reprocess_document(
    background: BackgroundTasks,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user)
):
    """重新运行文档摄取流水线。P0-3 修复：先校验 KB 所有权。"""
    doc = await _require_document_access(db, current_user, doc_id)

    if doc.status == "processing":
        raise ValidationException("文档正在处理中，请稍后再试")

    service = DocumentService(db)
    await service.clear_document_index(doc_id)

    await service.update_status(
        doc_id,
        status="pending",
        processing_info={"reprocess_requested_by": str(current_user.id)},
    )
    _dispatch_ingest(str(doc_id), background)
    return doc
