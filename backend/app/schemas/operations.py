"""Request/response schemas for operations dashboard and audit logs."""
from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class DashboardQuery(BaseModel):
    """Date range for dashboard metrics."""

    start: date
    end: date


class FeedbackSummary(BaseModel):
    """Message feedback summary."""

    positive: int
    negative: int
    total: int


class TopKBItem(BaseModel):
    """A knowledge base ranked by search + upload activity."""

    kb_id: str
    name: str
    search_count: int
    upload_count: int
    total: int


class DailyTrendItem(BaseModel):
    """Search/chat volume for a single day."""

    date: str
    search_count: int
    chat_count: int


class DashboardMetricsResponse(BaseModel):
    """Aggregated operations dashboard metrics."""

    search_count: int
    chat_count: int
    active_users: int
    feedback_summary: FeedbackSummary
    top_kbs: List[TopKBItem]
    daily_trend: List[DailyTrendItem]


class AuditLogQuery(BaseModel):
    """Filters for audit log list/export."""

    start: Optional[datetime] = None
    end: Optional[datetime] = None
    action: Optional[str] = None
    user_id: Optional[UUID] = None
    limit: int = Field(100, ge=1, le=1000)
    offset: int = Field(0, ge=0)


class AuditLogItem(BaseModel):
    """Single audit log entry returned by the list endpoint."""

    id: UUID
    timestamp: datetime
    action: str
    user_id: Optional[UUID]
    target_type: str
    target_id: Optional[UUID]
    user_security_level: Optional[str]
    intercepted: bool
    intercept_reason: Optional[str]
    latency_ms: Optional[int]

    class Config:
        from_attributes = True


class AuditLogListResponse(BaseModel):
    """Paginated audit log response."""

    total: int
    items: List[AuditLogItem]
