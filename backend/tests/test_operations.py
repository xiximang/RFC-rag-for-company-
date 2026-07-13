"""Tests for operations dashboard and audit log endpoints."""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import auth
from app.api.v1 import operations as ops_api
from app.schemas.user import UserResponse


FAKE_ADMIN_ID = uuid.uuid4()
FAKE_ADMIN = UserResponse(
    id=FAKE_ADMIN_ID,
    username="admin",
    email="admin@example.com",
    display_name="Admin",
    department="Engineering",
    security_level="L4",
    status="active",
    is_active=True,
)

FAKE_USER = UserResponse(
    id=uuid.uuid4(),
    username="alice",
    email="alice@example.com",
    display_name="Alice",
    department="Engineering",
    security_level="L0",
    status="active",
    is_active=True,
)


@pytest.fixture
def api_client():
    app = FastAPI()
    app.include_router(ops_api.router, prefix="/api/v1")
    app.dependency_overrides[ops_api.get_db] = lambda: AsyncMock()
    app.dependency_overrides[ops_api.get_current_user] = lambda: FAKE_ADMIN
    return TestClient(app)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def test_dashboard_success(api_client):
    with patch("app.api.v1.operations.operations_service") as mock_svc:
        mock_svc.get_dashboard_metrics = AsyncMock(
            return_value={
                "search_count": 120,
                "chat_count": 45,
                "active_users": 18,
                "feedback_summary": {
                    "positive": 30,
                    "negative": 5,
                    "total": 35,
                },
                "top_kbs": [
                    {
                        "kb_id": str(uuid.uuid4()),
                        "name": "Product KB",
                        "search_count": 50,
                        "upload_count": 10,
                        "total": 60,
                    }
                ],
                "daily_trend": [
                    {
                        "date": "2026-07-01",
                        "search_count": 30,
                        "chat_count": 10,
                    },
                    {
                        "date": "2026-07-02",
                        "search_count": 40,
                        "chat_count": 15,
                    },
                ],
            }
        )
        resp = api_client.get(
            "/api/v1/operations/dashboard?start=2026-07-01&end=2026-07-04"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["search_count"] == 120
    assert data["chat_count"] == 45
    assert data["active_users"] == 18
    assert data["feedback_summary"]["positive"] == 30
    assert data["feedback_summary"]["negative"] == 5
    assert data["feedback_summary"]["total"] == 35
    assert len(data["top_kbs"]) == 1
    assert len(data["daily_trend"]) == 2


def test_dashboard_forbidden_for_non_admin():
    app = FastAPI()
    app.include_router(ops_api.router, prefix="/api/v1")
    app.dependency_overrides[ops_api.get_db] = lambda: AsyncMock()
    app.dependency_overrides[ops_api.get_current_user] = lambda: FAKE_USER
    client = TestClient(app)

    resp = client.get(
        "/api/v1/operations/dashboard?start=2026-07-01&end=2026-07-04"
    )

    assert resp.status_code == 403
    assert "Admin access required" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Audit logs list
# ---------------------------------------------------------------------------
def test_audit_logs_list(api_client):
    log_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with patch("app.api.v1.operations.operations_service") as mock_svc:
        mock_svc.list_audit_logs = AsyncMock(
            return_value={
                "total": 1,
                "items": [
                    {
                        "id": log_id,
                        "timestamp": now,
                        "action": "search",
                        "user_id": FAKE_ADMIN_ID,
                        "target_type": "knowledge_base",
                        "target_id": kb_id,
                        "user_security_level": "L4",
                        "intercepted": False,
                        "intercept_reason": None,
                        "latency_ms": 120,
                    }
                ],
            }
        )
        resp = api_client.get(
            "/api/v1/operations/audit-logs?action=search&limit=10&offset=0"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["action"] == "search"
    assert UUID(data["items"][0]["id"]) == log_id


# ---------------------------------------------------------------------------
# Audit logs export
# ---------------------------------------------------------------------------
def test_export_audit_logs_csv(api_client):
    csv_header = (
        "timestamp,action,user_id,target_type,target_id,"
        "user_security_level,intercepted,intercept_reason,latency_ms"
    )
    csv_body = (
        "2026-07-01T00:00:00+00:00,search,"
        f"{FAKE_ADMIN_ID},knowledge_base,,L4,False,,120"
    )
    with patch("app.api.v1.operations.operations_service") as mock_svc:
        mock_svc.export_audit_logs = AsyncMock(
            return_value=(
                f"{csv_header}\n{csv_body}\n",
                "text/csv; charset=utf-8",
            )
        )
        resp = api_client.get(
            "/api/v1/operations/audit-logs/export?format=csv&action=search"
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "text/csv; charset=utf-8"
    assert "audit_logs.csv" in resp.headers["content-disposition"]
    text = resp.text
    assert csv_header in text
    assert "search" in text


def test_export_audit_logs_json(api_client):
    with patch("app.api.v1.operations.operations_service") as mock_svc:
        mock_svc.export_audit_logs = AsyncMock(
            return_value=(
                '[{"action":"search","intercepted":false}]',
                "application/json",
            )
        )
        resp = api_client.get(
            "/api/v1/operations/audit-logs/export?format=json"
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/json"
    data = resp.json()
    assert len(data) == 1
    assert data[0]["action"] == "search"
