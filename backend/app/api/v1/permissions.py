from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.v1.auth import get_current_user, is_admin
from app.database import get_db
from app.services.permission_service import PermissionService
from app.core.cache import CacheManager
from app.core.exceptions import NotFoundException, PermissionDeniedException, ValidationException
from app.schemas.permission import (
    FileTypePermissionCreate, DocumentPermissionCreate,
    FieldPermissionCreate, TagPermissionCreate,
    PermissionGrantRequest, PermissionRevokeRequest,
    PermissionBatchGrantRequest, PermissionBatchRevokeRequest,
    PermissionListResponse,
    PermissionCheckResponse, ObjectPermissionCheckResponse,
    PermissionValidationResponse,
)
from app.schemas.user import UserResponse

router = APIRouter(prefix="/permissions", tags=["权限管理"])

async def get_permission_service(db: AsyncSession = Depends(get_db)):
    cache = CacheManager()
    return PermissionService(db, cache)


def _perm_service_from_db(db: AsyncSession) -> PermissionService:
    return PermissionService(db, CacheManager())


@router.post("/file-type")
async def set_file_type_permission(
    perm_data: FileTypePermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """设置文件类型权限（统一走 grant_permission）。"""
    service = _perm_service_from_db(db)
    perm = await service.grant_permission(
        target_type=perm_data.target_type,
        target_id=perm_data.target_id,
        object_type="file_type",
        object_key=perm_data.file_type,
        permissions=perm_data.permissions or ["READ"],
    )
    return {"message": "文件类型权限设置成功", "permission_id": str(perm.id)}


@router.post("/document")
async def set_document_permission(
    perm_data: DocumentPermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """设置文档权限（统一走 grant_permission）。"""
    service = _perm_service_from_db(db)
    perm = await service.grant_permission(
        target_type=perm_data.target_type,
        target_id=perm_data.target_id,
        object_type="document",
        object_id=perm_data.doc_id,
        permission=perm_data.permission.upper(),
    )
    return {"message": "文档权限设置成功", "permission_id": str(perm.id)}


@router.post("/field")
async def set_field_permission(
    perm_data: FieldPermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """设置字段权限（统一走 grant_permission），支持 word/excel 细粒度配置。"""
    service = _perm_service_from_db(db)
    config = {}
    if perm_data.word_config:
        config["word_config"] = perm_data.word_config
    if perm_data.excel_config:
        config["excel_config"] = {k: v.model_dump() for k, v in perm_data.excel_config.items()}

    field_type = "word_paragraph" if perm_data.word_config else ("excel_sheet" if perm_data.excel_config else perm_data.file_type)
    perm = await service.grant_permission(
        target_type=perm_data.target_type,
        target_id=perm_data.target_id,
        object_type="field",
        object_id=perm_data.doc_id,
        object_key="*",
        permission="allow",
        field_type=field_type,
        config=config,
    )
    return {"message": "字段权限设置成功", "permission_id": str(perm.id)}


@router.post("/tag")
async def set_tag_permission(
    perm_data: TagPermissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """设置标签权限（统一走 grant_permission），支持多个标签。"""
    service = _perm_service_from_db(db)
    tag_ids = perm_data.allowed_tags or perm_data.denied_tags
    if not tag_ids:
        raise ValidationException("allowed_tags or denied_tags is required")

    # First tag becomes the primary object_id; remaining tags packed into object_key.
    primary_tag_id = tag_ids[0]
    extra_tag_ids = tag_ids[1:]
    perm = await service.grant_permission(
        target_type=perm_data.target_type,
        target_id=perm_data.target_id,
        object_type="tag",
        object_id=primary_tag_id,
        object_key=",".join(str(t) for t in extra_tag_ids) if extra_tag_ids else None,
        permission="allow" if perm_data.allowed_tags else "deny",
    )
    perm_id = perm[0].id if isinstance(perm, list) else perm.id
    return {"message": "标签权限设置成功", "permission_id": str(perm_id)}


@router.get("/check/{doc_id}", response_model=PermissionCheckResponse)
async def check_permission(
    doc_id: UUID,
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),
):
    perm = await service.check_document_permission(current_user.id, doc_id)
    level = await service.get_user_security_level(current_user.id)
    return PermissionCheckResponse(
        doc_id=doc_id,
        permission=perm,
        security_level=level
    )


@router.post("/grant")
async def grant_permission(
    request: PermissionGrantRequest,
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),
):
    """统一授权入口。P0-2 修复：仅 admin 可调用。"""
    if not is_admin(current_user):
        raise PermissionDeniedException("需要管理员权限才能授权")
    perm = await service.grant_permission(
        target_type=request.target_type,
        target_id=request.target_id,
        object_type=request.object_type,
        object_id=request.object_id,
        object_key=request.object_key,
        permission=request.permission,
        permissions=request.permissions,
        config=request.config,
        field_type=request.field_type,
    )
    return {"message": "授权成功", "permission_id": str(perm.id)}


@router.post("/revoke")
async def revoke_permission(
    request: PermissionRevokeRequest,
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),
):
    """统一撤销入口。"""
    deleted = await service.revoke_permission(
        target_type=request.target_type,
        target_id=request.target_id,
        object_type=request.object_type,
        object_id=request.object_id,
        object_key=request.object_key,
        permission=request.permission,
    )
    return {"message": "撤销成功", "deleted_count": deleted}


@router.post("/batch-grant")
async def grant_permissions_batch(
    request: PermissionBatchGrantRequest,
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),
):
    """批量授权入口。任意子项失败会回滚整个批次。P0-2 修复：仅 admin 可调用。"""
    if not is_admin(current_user):
        raise PermissionDeniedException("需要管理员权限才能批量授权")
    results = await service.grant_permissions_batch(request.items)
    return {
        "message": "批量授权成功",
        "granted_count": len(results),
        "permission_ids": [str(getattr(p, "id", "")) for p in results],
    }


@router.post("/batch-revoke")
async def revoke_permissions_batch(
    request: PermissionBatchRevokeRequest,
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),
):
    """批量撤销入口。任意子项失败会回滚整个批次。"""
    deleted_counts = await service.revoke_permissions_batch(request.items)
    return {
        "message": "批量撤销成功",
        "total_deleted": sum(deleted_counts),
    }


@router.get("/validate", response_model=PermissionValidationResponse)
async def validate_permission_inheritance(
    target_type: str = Query(..., description="user or group"),
    target_id: UUID = Query(..., description="target id"),
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),
):
    """检查指定目标的权限是否存在冲突（含用户与其所属用户组之间的继承冲突）。"""
    return await service.validate_permission_inheritance(target_type, target_id)


@router.get("/list", response_model=PermissionListResponse)
async def list_permissions(
    target_type: str = Query(..., description="user or group"),
    target_id: UUID = Query(..., description="target id"),
    object_type: Optional[str] = Query(None, description="file_type/document/field/tag"),
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),
):
    """查询指定用户或用户群的权限列表。"""
    perms = await service.list_permissions(
        target_type=target_type,
        target_id=target_id,
        object_type=object_type,
    )
    return PermissionListResponse(
        target_type=target_type,
        target_id=target_id,
        permissions=[
            {
                "id": p.id,
                "target_type": p.target_type,
                "target_id": UUID(p.target_id),
                "object_type": p.object_type,
                "object_id": p.object_id,
                "object_key": p.object_key,
                "permission": p.permission,
                "created_at": p.created_at,
            }
            for p in perms
        ],
    )


@router.get("/check/{object_type}/{object_id}", response_model=ObjectPermissionCheckResponse)
async def check_object_permission(
    object_type: str,
    object_id: str,
    field_path: Optional[str] = Query(None, description="可选字段路径，仅对 field 类型有效"),
    service: PermissionService = Depends(get_permission_service),
    current_user: UserResponse = Depends(get_current_user),
):
    """检查当前用户对某对象的最终权限。"""
    try:
        if object_type == "document":
            perm = await service.check_document_permission(current_user.id, UUID(object_id))
        elif object_type == "field":
            allowed = await service.check_field_access(
                current_user.id, UUID(object_id), field_path=field_path
            )
            perm = "allow" if allowed else "deny"
        elif object_type == "tag":
            perm = await service.check_tag_permission(current_user.id, UUID(object_id))
        elif object_type == "file_type":
            perm = await service.check_file_type_permission(current_user.id, object_id)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的对象类型: {object_type}")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    level = await service.get_user_security_level(current_user.id)
    return ObjectPermissionCheckResponse(
        object_type=object_type,
        object_id=object_id,
        permission=perm,
        security_level=level,
    )
