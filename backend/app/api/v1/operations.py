"""Operations dashboard and audit log endpoints."""
from datetime import date, datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user, is_admin
from app.database import get_db
from app.schemas.operations import AuditLogListResponse, DashboardMetricsResponse
from app.schemas.user import UserResponse
from app.services import operations_service

router = APIRouter(prefix="/operations", tags=["operations"])


async def require_admin_user(
    current_user: UserResponse = Depends(get_current_user),
) -> UserResponse:
    """Dependency that restricts access to administrators."""
    if not is_admin(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return current_user


@router.get("/dashboard", response_model=DashboardMetricsResponse)
async def get_dashboard(
    start: date,
    end: date,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_admin_user),
):
    """Return aggregated operations metrics for the given date range."""
    return await operations_service.get_dashboard_metrics(db, start, end)


@router.get("/audit-logs", response_model=AuditLogListResponse)
async def get_audit_logs(
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    action: Optional[str] = Query(None),
    user_id: Optional[UUID] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_admin_user),
):
    """List audit logs with optional filters and pagination."""
    return await operations_service.list_audit_logs(
        db, start, end, action, user_id, limit, offset
    )


@router.get("/audit-logs/export")
async def export_audit_logs(
    fmt: str = Query("json", alias="format", pattern="^(json|csv)$"),
    start: Optional[datetime] = Query(None),
    end: Optional[datetime] = Query(None),
    action: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(require_admin_user),
):
    """Export audit logs as JSON or CSV."""
    content, media_type = await operations_service.export_audit_logs(
        db, fmt, start, end, action
    )
    filename = f"audit_logs.{fmt}"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(
        iter([content.encode("utf-8")]),
        media_type=media_type,
        headers=headers,
    )
