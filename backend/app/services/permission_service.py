from datetime import datetime
from typing import List, Set, Dict, Optional, Any
from uuid import UUID
from sqlalchemy import select, or_, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.models.group import UserGroup
from app.models.permission import (
    FileTypePermission, DocumentPermission, FieldPermission,
    TagPermission, GroupPermission
)
from app.models.chunk import Chunk
from app.models.tag import Tag
from app.core.cache import CacheManager
from app.core.exceptions import NotFoundException, PermissionDeniedException, ValidationException
from app.retrieval.filters import VectorFilter
from app.services.group_service import GroupService
from app.schemas.permission import (
    PermissionGrantRequest,
    PermissionRevokeRequest,
    PermissionValidationResponse,
)

class UnifiedPermissionInfo:
    def __init__(
        self,
        id: UUID,
        target_type: str,
        target_id: str,
        object_type: str,
        object_id: Optional[str],
        object_key: Optional[str],
        permission: str,
        created_at: Optional[datetime] = None,
    ):
        self.id = id
        self.target_type = target_type
        self.target_id = target_id
        self.object_type = object_type
        self.object_id = object_id
        self.object_key = object_key
        self.permission = permission
        self.created_at = created_at

LEVEL_ORDER = {"L0": 0, "L1": 1, "L2": 2, "L3": 3, "L4": 4}

class PermissionResult:
    ALLOW = "ALLOW"
    DENY = "DENY"
    PARTIAL = "PARTIAL"
    NONE = "NONE"

class PermissionService:
    def __init__(self, db: AsyncSession, cache: CacheManager):
        self.db = db
        self.cache = cache
        self.group_service = GroupService(db)
    
    def _max_level(self, levels: List[str]) -> str:
        if not levels:
            return "L0"
        max_val = max(LEVEL_ORDER.get(l, 0) for l in levels)
        for k, v in LEVEL_ORDER.items():
            if v == max_val:
                return k
        return "L0"
    
    async def get_user_groups(self, user_id: UUID) -> List[UserGroup]:
        return await self.group_service.get_user_groups(user_id)
    
    async def get_user_security_level(self, user_id: UUID) -> str:
        """获取用户有效安全级别"""
        cached = await self.cache.get_user_security_level(str(user_id))
        if cached:
            return cached
        
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return "L0"
        
        groups = await self.get_user_groups(user_id)
        levels = [user.security_level or "L0"]
        levels.extend([g.max_security_level or "L0" for g in groups])
        
        effective = self._max_level(levels)
        await self.cache.set_user_security_level(str(user_id), effective)
        return effective
    
    async def get_user_allowed_file_types(self, user_id: UUID) -> Set[str]:
        """获取用户允许的文件类型"""
        cached = await self.cache.get_user_file_types(str(user_id))
        if cached:
            return cached
        
        groups = await self.get_user_groups(user_id)
        group_ids = [str(g.id) for g in groups]
        
        # FileTypePermission only stores role_id, so treat role_id as either the user id or a group id.
        grantee_ids = [str(user_id)] + group_ids
        result = await self.db.execute(
            select(FileTypePermission).where(FileTypePermission.role_id.in_(grantee_ids))
        )
        perms = result.scalars().all()
        
        # DENY优先
        denied = set()
        allowed = set()
        for p in perms:
            if "DENY" in p.permissions or "NONE" in p.permissions:
                denied.add(p.file_type)
            elif "READ" in p.permissions:
                allowed.add(p.file_type)
        
        final_allowed = allowed - denied
        await self.cache.set_user_file_types(str(user_id), final_allowed)
        return final_allowed
    
    async def check_document_permission(self, user_id: UUID, doc_id: UUID) -> str:
        """检查用户对文档的权限"""
        cached = await self.cache.get_user_doc_permission(str(user_id), str(doc_id))
        if cached:
            return cached
        
        groups = await self.get_user_groups(user_id)
        group_ids = [str(g.id) for g in groups]
        
        result = await self.db.execute(
            select(DocumentPermission).where(
                DocumentPermission.doc_id == doc_id,
                or_(
                    and_(DocumentPermission.grantee_type == "user", DocumentPermission.grantee_id == str(user_id)),
                    and_(DocumentPermission.grantee_type == "group", DocumentPermission.grantee_id.in_(group_ids))
                )
            )
        )
        perms = result.scalars().all()
        
        final_perm = PermissionResult.NONE
        for p in perms:
            if p.permission == "ADMIN":
                final_perm = "ADMIN"
                break
            elif p.permission == "WRITE":
                final_perm = "WRITE"
            elif p.permission == "READ" and final_perm == PermissionResult.NONE:
                final_perm = "READ"
            elif p.permission == "DENY":
                final_perm = PermissionResult.DENY
                break
        
        await self.cache.set_user_doc_permission(str(user_id), str(doc_id), final_perm)
        return final_perm
    
    async def get_user_denied_documents(self, user_id: UUID) -> Set[str]:
        """获取用户明确拒绝的文档ID"""
        groups = await self.get_user_groups(user_id)
        group_ids = [str(g.id) for g in groups]
        
        result = await self.db.execute(
            select(DocumentPermission.doc_id).where(
                DocumentPermission.permission == PermissionResult.DENY,
                or_(
                    and_(DocumentPermission.grantee_type == "user", DocumentPermission.grantee_id == str(user_id)),
                    and_(DocumentPermission.grantee_type == "group", DocumentPermission.grantee_id.in_(group_ids))
                )
            )
        )
        return {str(row[0]) for row in result.all()}
    
    async def get_user_allowed_tags(self, user_id: UUID) -> Set[str]:
        cached = await self.cache.get_user_tag_permission(str(user_id))
        if cached:
            return set(cached.get("allowed", []))
        
        groups = await self.get_user_groups(user_id)
        group_ids = [str(g.id) for g in groups]
        
        result = await self.db.execute(
            select(TagPermission).where(
                or_(
                    and_(TagPermission.grantee_type == "user", TagPermission.grantee_id == str(user_id)),
                    and_(TagPermission.grantee_type == "group", TagPermission.grantee_id.in_(group_ids))
                )
            )
        )
        perms = result.scalars().all()

        allowed = set()
        denied = set()
        for p in perms:
            if p.permission == "allow":
                allowed.add(str(p.tag_id))
            else:
                denied.add(str(p.tag_id))
        
        await self.cache.set_user_tag_permission(str(user_id), {"allowed": list(allowed), "denied": list(denied)})
        return allowed
    
    async def get_user_denied_tags(self, user_id: UUID) -> Set[str]:
        cached = await self.cache.get_user_tag_permission(str(user_id))
        if cached:
            return set(cached.get("denied", []))
        await self.get_user_allowed_tags(user_id)  # 预热缓存
        cached = await self.cache.get_user_tag_permission(str(user_id))
        return set(cached.get("denied", []))
    
    async def check_field_permission(self, user_id: UUID, chunk: Chunk) -> bool:
        """检查Chunk的字段级权限（默认拒绝，需明确授权）。

        检查逻辑：
        1. 如果有任何权限记录明确拒绝该用户/组，返回 False。
        2. 如果没有匹配任何允许记录，返回 False（默认拒绝）。
        3. 如果匹配允许记录，进一步检查 config 中的细粒度规则。
        """
        user_id_str = str(user_id)
        groups = await self.get_user_groups(user_id)
        group_ids = [str(g.id) for g in groups]

        position = (chunk.position_info or {}) if isinstance(chunk.position_info, dict) else {}

        result = await self.db.execute(
            select(FieldPermission).where(FieldPermission.doc_id == chunk.doc_id)
        )
        perms = result.scalars().all()

        # If no field permissions are configured for this document, default to
        # allowing access so that normal retrieval is not blocked.
        if not perms:
            return True

        explicitly_allowed = False
        for perm in perms:
            is_denied = user_id_str in (perm.denied_users or []) or any(
                gid in group_ids for gid in (perm.denied_groups or [])
            )
            if is_denied:
                return False

            is_allowed = user_id_str in (perm.allowed_users or []) or any(
                gid in group_ids for gid in (perm.allowed_groups or [])
            )
            if is_allowed:
                explicitly_allowed = True
                config = perm.config or {}
                if perm.field_type.startswith("excel") and config.get("excel_config"):
                    if not self._check_excel_permission(position, config["excel_config"]):
                        return False
                elif perm.field_type.startswith("word") and config.get("word_config"):
                    if not self._check_word_permission(position, config["word_config"]):
                        return False

        return explicitly_allowed
    
    def _check_excel_permission(self, position: Dict, config: Dict) -> bool:
        sheet_name = position.get("sheet_name")
        sheet_config = config.get("sheet_permissions", {}).get(sheet_name, {})
        access_level = sheet_config.get("access_level", "FULL")
        
        if access_level == "FULL":
            return True
        if access_level == "NONE":
            return False
        
        chunk_columns = set(position.get("columns", []))
        denied_cols = set(sheet_config.get("denied_columns", []))
        allowed_cols = set(sheet_config.get("allowed_columns", []))
        
        if chunk_columns & denied_cols:
            return False
        if allowed_cols and not (chunk_columns <= allowed_cols):
            return False
        
        return True
    
    def _check_word_permission(self, position: Dict, config: Dict) -> bool:
        denied_headings = config.get("denied_headings", [])
        heading_path = position.get("heading_path", "")
        for h in denied_headings:
            if h in heading_path:
                return False
        return True
    
    async def build_vector_filter(
        self,
        user_id: UUID,
        kb_ids: Optional[List[str]] = None,
        modalities: Optional[List[str]] = None,
    ) -> VectorFilter:
        """Build a backend-neutral permission filter for vector stores."""
        kb_ids = kb_ids or []
        modalities = modalities or []

        allowed_types = await self.get_user_allowed_file_types(user_id)
        if allowed_types:
            if modalities:
                allowed_types = allowed_types & set(modalities)
            effective_modalities = list(allowed_types)
        else:
            # Preserve legacy behavior: when no file-type permissions are
            # configured, no modality filter is emitted (all are allowed).
            effective_modalities = []

        denied_docs = await self.get_user_denied_documents(user_id)
        denied_tags = await self.get_user_denied_tags(user_id)

        return VectorFilter(
            kb_ids=[str(k) for k in kb_ids],
            modalities=effective_modalities,
            denied_doc_ids=list(denied_docs),
            denied_tags=list(denied_tags),
            status="active",
        )

    async def build_milvus_filter_expr(
        self,
        user_id: UUID,
        kb_ids: Optional[List[str]] = None,
        modalities: Optional[List[str]] = None,
    ) -> str:
        """生成Milvus权限过滤表达式 (backward-compatible wrapper)."""
        vector_filter = await self.build_vector_filter(user_id, kb_ids, modalities)
        return vector_filter.to_milvus_expr()

    # ------------------------------------------------------------------ #
    # Unified ACL operations
    # ------------------------------------------------------------------ #
    async def grant_permission(
        self,
        target_type: str,
        target_id: UUID,
        object_type: str,
        object_id: Optional[UUID] = None,
        object_key: Optional[str] = None,
        permission: Optional[str] = None,
        permissions: Optional[List[str]] = None,
        config: Optional[Dict[str, Any]] = None,
        field_type: Optional[str] = None,
        _commit: bool = True,
    ) -> Any:
        """Unified grant entry supporting user/group targets and file_type/document/field/tag objects."""
        target_id_str = str(target_id)

        if object_type == "file_type":
            file_type = object_key
            if not file_type:
                raise ValidationException("file_type object_key is required")
            perms = permissions or ([permission] if permission else ["READ"])
            # FileTypePermission uses role_id; treat target_id as role_id for unified ACL.
            perm = FileTypePermission(role_id=target_id_str, file_type=file_type, permissions=perms)
            self.db.add(perm)
        elif object_type == "document":
            if not object_id:
                raise ValidationException("document object_id is required")
            perm_value = (permission or "READ").upper()
            perm = DocumentPermission(
                doc_id=object_id,
                grantee_type=target_type,
                grantee_id=target_id_str,
                permission=perm_value,
            )
            self.db.add(perm)
        elif object_type == "field":
            if not object_id:
                raise ValidationException("field object_id (doc_id) is required")
            field_path = object_key or "*"
            field_type_val = field_type or "excel_sheet"
            allowed_users: List[str] = []
            denied_users: List[str] = []
            allowed_groups: List[str] = []
            denied_groups: List[str] = []
            is_deny = permission and permission.lower() == "deny"
            if target_type == "user":
                if is_deny:
                    denied_users = [target_id_str]
                else:
                    allowed_users = [target_id_str]
            else:
                if is_deny:
                    denied_groups = [target_id_str]
                else:
                    allowed_groups = [target_id_str]
            perm = FieldPermission(
                doc_id=object_id,
                field_path=field_path,
                field_type=field_type_val,
                allowed_users=allowed_users,
                allowed_groups=allowed_groups,
                denied_users=denied_users,
                denied_groups=denied_groups,
                config=config or {},
            )
            self.db.add(perm)
        elif object_type == "tag":
            # 支持一次性授予/撤销多个标签；object_key 可以是逗号分隔的标签 ID 列表
            tag_ids = []
            if object_id:
                tag_ids.append(str(object_id))
            if object_key:
                for raw_id in object_key.split(","):
                    raw_id = raw_id.strip()
                    if raw_id:
                        tag_ids.append(raw_id)
            if not tag_ids:
                raise ValidationException("tag object_id or object_key is required")
            perm_value = permission or "allow"
            perms = []
            for tag_id in tag_ids:
                perm = TagPermission(
                    tag_id=UUID(tag_id),
                    grantee_type=target_type,
                    grantee_id=target_id_str,
                    permission=perm_value,
                )
                self.db.add(perm)
                perms.append(perm)
            if _commit:
                await self.db.commit()
                for perm in perms:
                    await self.db.refresh(perm)
            await self.invalidate_target_cache(target_type, target_id)
            return perms[0] if len(perms) == 1 else perms
        else:
            raise ValidationException(f"unsupported object_type: {object_type}")

        if _commit:
            await self.db.commit()
            await self.db.refresh(perm)
        await self.invalidate_target_cache(target_type, target_id)
        if object_id:
            await self.cache.invalidate_document_cache(str(object_id))
        return perm

    async def revoke_permission(
        self,
        target_type: str,
        target_id: UUID,
        object_type: str,
        object_id: Optional[UUID] = None,
        object_key: Optional[str] = None,
        permission: Optional[str] = None,
        _commit: bool = True,
    ) -> int:
        """Unified revoke entry. Returns the number of permission records removed."""
        target_id_str = str(target_id)
        deleted_count = 0

        if object_type == "file_type":
            file_type = object_key
            if not file_type:
                raise ValidationException("file_type object_key is required")
            result = await self.db.execute(
                select(FileTypePermission).where(
                    FileTypePermission.role_id == target_id_str,
                    FileTypePermission.file_type == file_type,
                )
            )
            for perm in result.scalars().all():
                await self.db.delete(perm)
                deleted_count += 1
        elif object_type == "document":
            if not object_id:
                raise ValidationException("document object_id is required")
            stmt = delete(DocumentPermission).where(
                DocumentPermission.doc_id == object_id,
                DocumentPermission.grantee_type == target_type,
                DocumentPermission.grantee_id == target_id_str,
            )
            if permission:
                stmt = stmt.where(DocumentPermission.permission == permission.upper())
            result = await self.db.execute(stmt)
            deleted_count = result.rowcount
        elif object_type == "field":
            if not object_id:
                raise ValidationException("field object_id (doc_id) is required")
            result = await self.db.execute(
                select(FieldPermission).where(FieldPermission.doc_id == object_id)
            )
            for perm in result.scalars().all():
                if target_type == "user":
                    matches = target_id_str in (perm.allowed_users or []) or target_id_str in (perm.denied_users or [])
                else:
                    matches = target_id_str in (perm.allowed_groups or []) or target_id_str in (perm.denied_groups or [])
                if matches:
                    await self.db.delete(perm)
                    deleted_count += 1
        elif object_type == "tag":
            if not object_id:
                raise ValidationException("tag object_id is required")
            stmt = delete(TagPermission).where(
                TagPermission.tag_id == object_id,
                TagPermission.grantee_type == target_type,
                TagPermission.grantee_id == target_id_str,
            )
            if permission:
                stmt = stmt.where(TagPermission.permission == permission.lower())
            result = await self.db.execute(stmt)
            deleted_count = result.rowcount
        else:
            raise ValidationException(f"unsupported object_type: {object_type}")

        if _commit:
            await self.db.commit()
        await self.invalidate_target_cache(target_type, target_id)
        if object_id:
            await self.cache.invalidate_document_cache(str(object_id))
        return deleted_count

    async def list_permissions(
        self,
        target_type: str,
        target_id: UUID,
        object_type: Optional[str] = None,
    ) -> List[UnifiedPermissionInfo]:
        """List permissions granted to a user or group, optionally filtered by object type."""
        target_id_str = str(target_id)
        results: List[UnifiedPermissionInfo] = []

        object_types = [object_type] if object_type else ["file_type", "document", "field", "tag"]

        if "file_type" in object_types:
            result = await self.db.execute(
                select(FileTypePermission).where(FileTypePermission.role_id == target_id_str)
            )
            for perm in result.scalars().all():
                results.append(
                    UnifiedPermissionInfo(
                        id=perm.id,
                        target_type=target_type,
                        target_id=target_id_str,
                        object_type="file_type",
                        object_id=None,
                        object_key=perm.file_type,
                        permission=",".join(perm.permissions or []),
                        created_at=perm.created_at,
                    )
                )

        if "document" in object_types:
            result = await self.db.execute(
                select(DocumentPermission).where(
                    DocumentPermission.grantee_type == target_type,
                    DocumentPermission.grantee_id == target_id_str,
                )
            )
            for perm in result.scalars().all():
                results.append(
                    UnifiedPermissionInfo(
                        id=perm.id,
                        target_type=target_type,
                        target_id=target_id_str,
                        object_type="document",
                        object_id=str(perm.doc_id),
                        object_key=None,
                        permission=perm.permission,
                        created_at=perm.created_at,
                    )
                )

        if "field" in object_types:
            result = await self.db.execute(select(FieldPermission))
            for perm in result.scalars().all():
                if target_type == "user":
                    is_allowed = target_id_str in (perm.allowed_users or [])
                    is_denied = target_id_str in (perm.denied_users or [])
                else:
                    is_allowed = target_id_str in (perm.allowed_groups or [])
                    is_denied = target_id_str in (perm.denied_groups or [])
                if is_allowed or is_denied:
                    results.append(
                        UnifiedPermissionInfo(
                            id=perm.id,
                            target_type=target_type,
                            target_id=target_id_str,
                            object_type="field",
                            object_id=str(perm.doc_id),
                            object_key=perm.field_path,
                            permission="deny" if is_denied else "allow",
                            created_at=perm.created_at,
                        )
                    )

        if "tag" in object_types:
            result = await self.db.execute(
                select(TagPermission).where(
                    TagPermission.grantee_type == target_type,
                    TagPermission.grantee_id == target_id_str,
                )
            )
            for perm in result.scalars().all():
                results.append(
                    UnifiedPermissionInfo(
                        id=perm.id,
                        target_type=target_type,
                        target_id=target_id_str,
                        object_type="tag",
                        object_id=str(perm.tag_id),
                        object_key=None,
                        permission=perm.permission,
                        created_at=perm.created_at,
                    )
                )

        return results

    async def check_file_type_permission(self, user_id: UUID, file_type: str) -> str:
        """Return effective permission for a file type (DENY/READ/WRITE/ADMIN/NONE)."""
        allowed = await self.get_user_allowed_file_types(user_id)
        return "READ" if file_type in allowed else "NONE"

    async def check_tag_permission(self, user_id: UUID, tag_id: UUID) -> str:
        """Return effective permission for a tag (allow/deny)."""
        cached = await self.cache.get_user_tag_permission(str(user_id))
        if cached:
            denied = set(cached.get("denied", []))
            allowed = set(cached.get("allowed", []))
        else:
            allowed = await self.get_user_allowed_tags(user_id)
            denied = await self.get_user_denied_tags(user_id)

        tag_id_str = str(tag_id)
        if tag_id_str in denied:
            return "deny"
        if tag_id_str in allowed:
            return "allow"
        return "none"

    async def check_field_access(
        self,
        user_id: UUID,
        doc_id: UUID,
        field_path: Optional[str] = None,
    ) -> bool:
        """Check whether a user can access a field path within a document."""
        user_id_str = str(user_id)
        groups = await self.get_user_groups(user_id)
        group_ids = [str(g.id) for g in groups]

        result = await self.db.execute(
            select(FieldPermission).where(FieldPermission.doc_id == doc_id)
        )
        perms = result.scalars().all()

        for perm in perms:
            denied = user_id_str in (perm.denied_users or []) or any(
                gid in group_ids for gid in (perm.denied_groups or [])
            )
            if denied:
                return False
            if field_path and perm.field_path != "*" and perm.field_path != field_path:
                continue
            allowed = user_id_str in (perm.allowed_users or []) or any(
                gid in group_ids for gid in (perm.allowed_groups or [])
            )
            if allowed:
                return True

        return False

    async def invalidate_target_cache(self, target_type: str, target_id: UUID) -> None:
        """Invalidate cache for a target user or all members of a target group."""
        if target_type == "user":
            await self.cache.invalidate_user_cache(str(target_id))
        elif target_type == "group":
            try:
                group = await self.group_service.get_group(target_id)
                member_ids = set(group.member_ids or [])
                for member_id in member_ids:
                    await self.cache.invalidate_user_cache(member_id)
            except (NotFoundException, AttributeError):
                pass

    # ------------------------------------------------------------------ #
    # Batch ACL operations
    # ------------------------------------------------------------------ #
    async def grant_permissions_batch(
        self, items: List[PermissionGrantRequest]
    ) -> List[Any]:
        """Batch grant permissions atomically.

        Iterates over ``items`` and calls :meth:`grant_permission` for each one.
        If any item fails, the whole transaction is rolled back and a
        ``ValidationException`` is raised.
        """
        results: List[Any] = []
        try:
            async with self.db.begin():
                for item in items:
                    result = await self.grant_permission(
                        _commit=False,
                        target_type=item.target_type,
                        target_id=item.target_id,
                        object_type=item.object_type,
                        object_id=item.object_id,
                        object_key=item.object_key,
                        permission=item.permission,
                        permissions=item.permissions,
                        config=item.config,
                        field_type=item.field_type,
                    )
                    results.append(result)
        except Exception as exc:
            raise ValidationException(f"批量授权失败: {exc}") from exc
        return results

    async def revoke_permissions_batch(
        self, items: List[PermissionRevokeRequest]
    ) -> List[int]:
        """Batch revoke permissions atomically.

        Iterates over ``items`` and calls :meth:`revoke_permission` for each one.
        If any item fails, the whole transaction is rolled back and a
        ``ValidationException`` is raised.
        """
        results: List[int] = []
        try:
            async with self.db.begin():
                for item in items:
                    deleted = await self.revoke_permission(
                        _commit=False,
                        target_type=item.target_type,
                        target_id=item.target_id,
                        object_type=item.object_type,
                        object_id=item.object_id,
                        object_key=item.object_key,
                        permission=item.permission,
                    )
                    results.append(deleted)
        except Exception as exc:
            raise ValidationException(f"批量撤销失败: {exc}") from exc
        return results

    async def validate_permission_inheritance(
        self, target_type: str, target_id: UUID
    ) -> PermissionValidationResponse:
        """Detect conflicting permission assignments for a target.

        Conflicts include:
        - Both positive (READ/WRITE/ADMIN/allow) and negative (NONE/DENY)
          permissions on the same object for the same target.
        - Conflicts between a user's directly assigned permissions and the
          permissions inherited from the user's groups.
        """
        all_perms = await self.list_permissions(target_type, target_id)

        # Include group permissions when validating a user so that
        # user/group conflicts are also reported.
        if target_type == "user":
            groups = await self.get_user_groups(target_id)
            for group in groups:
                group_perms = await self.list_permissions("group", group.id)
                for gp in group_perms:
                    all_perms.append(
                        UnifiedPermissionInfo(
                            id=gp.id,
                            target_type="group",
                            target_id=str(group.id),
                            object_type=gp.object_type,
                            object_id=gp.object_id,
                            object_key=gp.object_key,
                            permission=gp.permission,
                            created_at=gp.created_at,
                        )
                    )

        conflicts = self._detect_permission_conflicts(all_perms)
        return PermissionValidationResponse(
            valid=len(conflicts) == 0, conflicts=conflicts
        )

    def _detect_permission_conflicts(
        self, perms: List[UnifiedPermissionInfo]
    ) -> List[Dict[str, Any]]:
        """Group permissions by object and detect contradictory values."""
        grouped: Dict[tuple, List[UnifiedPermissionInfo]] = {}
        for p in perms:
            obj_key = p.object_key if p.object_id is None else p.object_id
            key = (p.object_type, obj_key)
            grouped.setdefault(key, []).append(p)

        conflicts: List[Dict[str, Any]] = []
        for (obj_type, obj_key), group in grouped.items():
            is_conflict = False
            if obj_type == "file_type":
                # file_type permissions are stored as comma-separated values.
                values = set()
                for p in group:
                    values.update(p.permission.upper().split(","))
                positive = values & {"READ", "WRITE", "ADMIN", "UPLOAD", "DELETE"}
                negative = values & {"NONE", "DENY"}
                is_conflict = bool(positive and negative)
            elif obj_type == "document":
                values = {p.permission.upper() for p in group}
                positive = values & {"READ", "WRITE", "ADMIN"}
                negative = values & {"NONE", "DENY"}
                is_conflict = bool(positive and negative)
            elif obj_type in ("tag", "field"):
                values = {p.permission.upper() for p in group}
                allows = values & {"ALLOW", "READ"}
                denies = values & {"DENY", "NONE"}
                is_conflict = bool(allows and denies)
            else:
                values = {p.permission.upper() for p in group}

            if is_conflict:
                conflicts.append(
                    {
                        "object_type": obj_type,
                        "object_id": obj_key,
                        "permissions": sorted(values),
                        "sources": [
                            {
                                "target_type": p.target_type,
                                "target_id": p.target_id,
                                "permission": p.permission,
                            }
                            for p in group
                        ],
                    }
                )

        return conflicts
