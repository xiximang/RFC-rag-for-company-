"""Operations dashboard and audit log service."""
import csv
import io
import json
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.conversation import Conversation
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.message import Message
from app.models.search_history import SearchHistory


def _to_datetime_range(start: date, end: date) -> Tuple[datetime, datetime]:
    """Convert inclusive date range to timezone-aware datetimes."""
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(
        end.year, end.month, end.day, 23, 59, 59, 999999, tzinfo=timezone.utc
    )
    return start_dt, end_dt


async def get_dashboard_metrics(
    db: AsyncSession, start: date, end: date
) -> dict:
    """Return operations dashboard metrics for the inclusive date range."""
    start_dt, end_dt = _to_datetime_range(start, end)

    # Search volume
    search_result = await db.execute(
        select(func.count(SearchHistory.id)).where(
            SearchHistory.created_at >= start_dt,
            SearchHistory.created_at <= end_dt,
        )
    )
    search_count = search_result.scalar() or 0

    # Chat/answer volume: assistant messages created in range
    chat_result = await db.execute(
        select(func.count(Message.id)).where(
            Message.role == "assistant",
            Message.created_at >= start_dt,
            Message.created_at <= end_dt,
        )
    )
    chat_count = chat_result.scalar() or 0

    # Active users: distinct user_ids across searches and conversations
    search_users = (
        select(SearchHistory.user_id)
        .where(
            SearchHistory.created_at >= start_dt,
            SearchHistory.created_at <= end_dt,
        )
        .subquery()
    )
    conv_users = (
        select(Conversation.user_id)
        .where(
            Conversation.created_at >= start_dt,
            Conversation.created_at <= end_dt,
        )
        .subquery()
    )
    union_subq = select(search_users.c.user_id).union(
        select(conv_users.c.user_id)
    ).subquery()
    active_result = await db.execute(
        select(func.count(union_subq.c.user_id)).select_from(union_subq)
    )
    active_users = active_result.scalar() or 0

    # Feedback summary
    feedback_result = await db.execute(
        select(Message.feedback_rating, func.count(Message.id))
        .where(
            Message.role == "assistant",
            Message.feedback_rating.isnot(None),
            Message.created_at >= start_dt,
            Message.created_at <= end_dt,
        )
        .group_by(Message.feedback_rating)
    )
    feedback_map = {rating: count for rating, count in feedback_result.all()}
    positive = feedback_map.get(1, 0)
    negative = feedback_map.get(-1, 0)
    feedback_summary = {
        "positive": positive,
        "negative": negative,
        "total": positive + negative,
    }

    # Top knowledge bases by search + upload activity
    kb_result = await db.execute(select(KnowledgeBase.id, KnowledgeBase.name))
    kb_stats = {
        str(kb_id): {"name": name, "search_count": 0, "upload_count": 0}
        for kb_id, name in kb_result.all()
    }

    search_histories = await db.execute(
        select(SearchHistory.kb_ids).where(
            SearchHistory.created_at >= start_dt,
            SearchHistory.created_at <= end_dt,
        )
    )
    for (kb_ids,) in search_histories.all():
        for kb_id in kb_ids or []:
            if kb_id in kb_stats:
                kb_stats[kb_id]["search_count"] += 1

    doc_result = await db.execute(
        select(Document.kb_id).where(
            Document.created_at >= start_dt,
            Document.created_at <= end_dt,
        )
    )
    for (kb_id,) in doc_result.all():
        kb_id_str = str(kb_id) if kb_id else None
        if kb_id_str and kb_id_str in kb_stats:
            kb_stats[kb_id_str]["upload_count"] += 1

    top_kbs = sorted(
        [
            {
                "kb_id": kb_id,
                "name": data["name"],
                "search_count": data["search_count"],
                "upload_count": data["upload_count"],
                "total": data["search_count"] + data["upload_count"],
            }
            for kb_id, data in kb_stats.items()
        ],
        key=lambda item: item["total"],
        reverse=True,
    )[:10]

    # Daily trend: search + chat counts per day
    days = (end - start).days + 1
    trend_map: dict[str, dict] = {}
    for i in range(days):
        d = start + timedelta(days=i)
        trend_map[d.isoformat()] = {"search_count": 0, "chat_count": 0}

    search_by_date = await db.execute(
        select(
            cast(SearchHistory.created_at, Date).label("day"),
            func.count(SearchHistory.id),
        )
        .where(
            SearchHistory.created_at >= start_dt,
            SearchHistory.created_at <= end_dt,
        )
        .group_by("day")
    )
    for day, count in search_by_date.all():
        key = day.isoformat() if isinstance(day, date) else str(day)
        if key in trend_map:
            trend_map[key]["search_count"] = count

    chat_by_date = await db.execute(
        select(
            cast(Message.created_at, Date).label("day"),
            func.count(Message.id),
        )
        .where(
            Message.role == "assistant",
            Message.created_at >= start_dt,
            Message.created_at <= end_dt,
        )
        .group_by("day")
    )
    for day, count in chat_by_date.all():
        key = day.isoformat() if isinstance(day, date) else str(day)
        if key in trend_map:
            trend_map[key]["chat_count"] = count

    daily_trend = [
        {
            "date": d,
            "search_count": trend_map[d]["search_count"],
            "chat_count": trend_map[d]["chat_count"],
        }
        for d in sorted(trend_map.keys())
    ]

    return {
        "search_count": search_count,
        "chat_count": chat_count,
        "active_users": active_users,
        "feedback_summary": feedback_summary,
        "top_kbs": top_kbs,
        "daily_trend": daily_trend,
    }


def _build_audit_filters(
    start: Optional[datetime],
    end: Optional[datetime],
    action: Optional[str],
    user_id: Optional[UUID],
) -> List:
    """Return a list of SQLAlchemy filter conditions for audit logs."""
    filters = []
    if start:
        filters.append(AuditLog.timestamp >= start)
    if end:
        filters.append(AuditLog.timestamp <= end)
    if action:
        filters.append(AuditLog.action == action)
    if user_id:
        filters.append(AuditLog.user_id == user_id)
    return filters


async def list_audit_logs(
    db: AsyncSession,
    start: Optional[datetime],
    end: Optional[datetime],
    action: Optional[str],
    user_id: Optional[UUID],
    limit: int,
    offset: int,
) -> dict:
    """Return a paginated list of audit logs matching the filters."""
    filters = _build_audit_filters(start, end, action, user_id)

    count_result = await db.execute(
        select(func.count(AuditLog.id)).where(*filters)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    items = list(result.scalars().all())

    return {"total": total, "items": items}


async def export_audit_logs(
    db: AsyncSession,
    fmt: str,
    start: Optional[datetime],
    end: Optional[datetime],
    action: Optional[str],
) -> Tuple[str, str]:
    """Export audit logs as JSON or CSV.

    Returns a tuple of (content, media_type).
    """
    filters = _build_audit_filters(start, end, action, None)
    result = await db.execute(
        select(AuditLog)
        .where(*filters)
        .order_by(AuditLog.timestamp.desc())
    )
    items: List[AuditLog] = list(result.scalars().all())

    csv_columns = [
        "timestamp",
        "action",
        "user_id",
        "target_type",
        "target_id",
        "user_security_level",
        "intercepted",
        "intercept_reason",
        "latency_ms",
    ]

    if fmt == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(csv_columns)
        for item in items:
            writer.writerow(
                [
                    item.timestamp.isoformat() if item.timestamp else "",
                    item.action,
                    str(item.user_id) if item.user_id else "",
                    item.target_type,
                    str(item.target_id) if item.target_id else "",
                    item.user_security_level or "",
                    "true" if item.intercepted else "false",
                    item.intercept_reason or "",
                    item.latency_ms if item.latency_ms is not None else "",
                ]
            )
        return output.getvalue(), "text/csv; charset=utf-8"

    # JSON export
    payload = [
        {
            "timestamp": item.timestamp.isoformat() if item.timestamp else None,
            "action": item.action,
            "user_id": str(item.user_id) if item.user_id else None,
            "target_type": item.target_type,
            "target_id": str(item.target_id) if item.target_id else None,
            "user_security_level": item.user_security_level,
            "intercepted": item.intercepted,
            "intercept_reason": item.intercept_reason,
            "latency_ms": item.latency_ms,
        }
        for item in items
    ]
    return json.dumps(payload, ensure_ascii=False, indent=2), "application/json"
