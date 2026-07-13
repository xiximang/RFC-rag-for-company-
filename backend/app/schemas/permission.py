from datetime import datetime
from typing import Optional, List, Dict, Any, Literal
from uuid import UUID
from pydantic import BaseModel

PermissionTargetType = Literal["user", "group"]
PermissionObjectType = Literal["file_type", "document", "field", "tag"]

class FileTypePermissionCreate(BaseModel):
    target_type: str = "group"  # user/group/role
    target_id: UUID
    file_type: str
    permissions: List[str] = ["READ"]

class DocumentPermissionCreate(BaseModel):
    target_type: str = "group"
    target_id: UUID
    doc_id: UUID
    permission: str  # NONE/READ/WRITE/ADMIN

class ExcelSheetPermission(BaseModel):
    access_level: str = "PARTIAL"  # FULL/PARTIAL/NONE
    allowed_columns: List[str] = []
    denied_columns: List[str] = []
    allowed_rows: Optional[tuple] = None
    row_filter: Optional[str] = None

class FieldPermissionCreate(BaseModel):
    target_type: str = "group"
    target_id: UUID
    doc_id: UUID
    file_type: str  # word/excel
    word_config: Optional[Dict[str, Any]] = None
    excel_config: Optional[Dict[str, ExcelSheetPermission]] = None

class TagPermissionCreate(BaseModel):
    target_type: str = "group"
    target_id: UUID
    allowed_tags: List[UUID] = []
    denied_tags: List[UUID] = []

class PermissionGrantRequest(BaseModel):
    target_type: PermissionTargetType
    target_id: UUID
    object_type: PermissionObjectType
    object_id: Optional[UUID] = None
    object_key: Optional[str] = None  # file_type string or field_path
    permission: str = "READ"  # READ/WRITE/ADMIN/NONE/allow/deny
    permissions: Optional[List[str]] = None  # for file_type
    field_type: Optional[str] = None  # word_paragraph/excel_cell/excel_column/excel_sheet
    config: Optional[Dict[str, Any]] = None  # extra config for field permissions

class PermissionRevokeRequest(BaseModel):
    target_type: PermissionTargetType
    target_id: UUID
    object_type: PermissionObjectType
    object_id: Optional[UUID] = None
    object_key: Optional[str] = None
    permission: Optional[str] = None  # if None, revoke all matching permissions

class PermissionBatchGrantRequest(BaseModel):
    items: List[PermissionGrantRequest]

class PermissionBatchRevokeRequest(BaseModel):
    items: List[PermissionRevokeRequest]

class PermissionValidationResponse(BaseModel):
    valid: bool
    conflicts: List[Dict[str, Any]] = []

class PermissionListRequest(BaseModel):
    target_type: PermissionTargetType
    target_id: UUID
    object_type: Optional[PermissionObjectType] = None

class PermissionInfo(BaseModel):
    id: UUID
    target_type: str
    target_id: UUID
    object_type: str
    object_id: Optional[str] = None
    object_key: Optional[str] = None
    permission: str
    created_at: Optional[datetime] = None

class PermissionListResponse(BaseModel):
    target_type: str
    target_id: UUID
    permissions: List[PermissionInfo]

class PermissionCheckResponse(BaseModel):
    doc_id: UUID
    permission: str  # NONE/READ/WRITE/ADMIN
    security_level: str

class ObjectPermissionCheckResponse(BaseModel):
    object_type: str
    object_id: str
    permission: str
    security_level: str
