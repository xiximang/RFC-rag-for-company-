"""Tests for unified ACL permission API and service."""
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.services.permission_service import PermissionService, UnifiedPermissionInfo
from app.core.cache import CacheManager
from app.core.exceptions import ValidationException
from app.schemas.permission import (
    PermissionGrantRequest,
    PermissionRevokeRequest,
    PermissionListRequest,
    ObjectPermissionCheckResponse,
    PermissionValidationResponse,
)


class AsyncMockContextManager:
    """Minimal async context manager for mocking SQLAlchemy transactions."""

    def __init__(self, enter_value=None):
        self.enter_value = enter_value

    async def __aenter__(self):
        return self.enter_value

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def fake_db():
    """Return a mocked AsyncSession."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.add = MagicMock()
    db.execute = AsyncMock()
    db.delete = AsyncMock()
    db.begin = MagicMock(return_value=AsyncMockContextManager())
    return db


@pytest.fixture
def fake_cache():
    """Return a mocked CacheManager."""
    cache = AsyncMock(spec=CacheManager)
    cache.invalidate_user_cache = AsyncMock(return_value=1)
    cache.invalidate_document_cache = AsyncMock(return_value=1)
    cache.get_user_security_level = AsyncMock(return_value=None)
    cache.set_user_security_level = AsyncMock(return_value=True)
    return cache


@pytest.fixture
def permission_service(fake_db, fake_cache):
    return PermissionService(fake_db, fake_cache)


class TestPermissionServiceGrant:
    async def test_grant_document_to_user(self, permission_service, fake_db):
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        permission_service.group_service.get_user_groups = AsyncMock(return_value=[])

        perm = await permission_service.grant_permission(
            target_type="user",
            target_id=user_id,
            object_type="document",
            object_id=doc_id,
            permission="READ",
        )

        assert fake_db.add.called
        added = fake_db.add.call_args[0][0]
        assert str(added.grantee_id) == str(user_id)
        assert str(added.doc_id) == str(doc_id)
        assert added.permission == "READ"
        fake_db.commit.assert_awaited()

    async def test_grant_file_type_to_group(self, permission_service, fake_db):
        group_id = uuid.uuid4()

        perm = await permission_service.grant_permission(
            target_type="group",
            target_id=group_id,
            object_type="file_type",
            object_key="PDF",
            permissions=["READ", "UPLOAD"],
        )

        added = fake_db.add.call_args[0][0]
        assert added.role_id == str(group_id)
        assert added.file_type == "PDF"
        assert added.permissions == ["READ", "UPLOAD"]

    async def test_grant_field_to_user_deny(self, permission_service, fake_db):
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        perm = await permission_service.grant_permission(
            target_type="user",
            target_id=user_id,
            object_type="field",
            object_id=doc_id,
            object_key="Sheet1!A1",
            permission="deny",
            field_type="excel_cell",
        )

        added = fake_db.add.call_args[0][0]
        assert str(added.doc_id) == str(doc_id)
        assert added.denied_users == [str(user_id)]
        assert added.field_type == "excel_cell"


class TestPermissionServiceRevoke:
    async def test_revoke_document_clears_cache(self, permission_service, fake_db, fake_cache):
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        result_mock = MagicMock()
        result_mock.rowcount = 1
        fake_db.execute.return_value = result_mock

        deleted = await permission_service.revoke_permission(
            target_type="user",
            target_id=user_id,
            object_type="document",
            object_id=doc_id,
        )

        fake_cache.invalidate_user_cache.assert_awaited_with(str(user_id))
        fake_cache.invalidate_document_cache.assert_awaited_with(str(doc_id))


class TestPermissionServiceList:
    async def test_list_permissions_for_user(self, permission_service, fake_db):
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        perm_id = uuid.uuid4()

        perm = MagicMock()
        perm.id = perm_id
        perm.doc_id = doc_id
        perm.grantee_type = "user"
        perm.grantee_id = str(user_id)
        perm.permission = "WRITE"
        perm.created_at = datetime.now()

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [perm]
        fake_db.execute.return_value = result_mock

        results = await permission_service.list_permissions(
            target_type="user", target_id=user_id, object_type="document"
        )

        assert len(results) == 1
        assert results[0].object_type == "document"
        assert results[0].permission == "WRITE"


class TestPermissionSchemas:
    def test_grant_request_valid(self):
        req = PermissionGrantRequest(
            target_type="user",
            target_id=uuid.uuid4(),
            object_type="document",
            object_id=uuid.uuid4(),
            permission="READ",
        )
        assert req.target_type == "user"

    def test_revoke_request_valid(self):
        req = PermissionRevokeRequest(
            target_type="group",
            target_id=uuid.uuid4(),
            object_type="file_type",
            object_key="PDF",
        )
        assert req.object_key == "PDF"


class TestPermissionApiSmoke:
    def test_check_response_schema(self):
        resp = ObjectPermissionCheckResponse(
            object_type="document",
            object_id=str(uuid.uuid4()),
            permission="READ",
            security_level="L2",
        )
        assert resp.permission == "READ"


class TestPermissionApiEndpoints:
    @pytest.fixture
    def api_client(self):
        from fastapi import FastAPI
        from app.api.v1.permissions import router as permissions_router, get_permission_service
        from app.api.v1.auth import get_current_user
        from app.schemas.user import UserResponse

        app = FastAPI()
        app.include_router(permissions_router, prefix="/api/v1")

        user_id = uuid.uuid4()
        app.dependency_overrides[get_current_user] = lambda: UserResponse(
            id=user_id,
            username="alice",
            email="alice@example.com",
            display_name="Alice",
            department="Engineering",
            security_level="L2",
            status="active",
            is_active=True,
        )

        fake_service = AsyncMock()
        fake_perm = MagicMock()
        fake_perm.id = uuid.uuid4()
        fake_service.grant_permission = AsyncMock(return_value=fake_perm)
        fake_service.revoke_permission = AsyncMock(return_value=1)
        fake_service.list_permissions = AsyncMock(return_value=[])
        fake_service.check_document_permission = AsyncMock(return_value="READ")
        fake_service.check_field_access = AsyncMock(return_value=True)
        fake_service.check_tag_permission = AsyncMock(return_value="allow")
        fake_service.check_file_type_permission = AsyncMock(return_value="READ")
        fake_service.get_user_security_level = AsyncMock(return_value="L2")
        app.dependency_overrides[get_permission_service] = lambda: fake_service

        with TestClient(app) as client:
            yield client, fake_service

    def test_grant_endpoint(self, api_client):
        client, fake_service = api_client
        resp = client.post(
            "/api/v1/permissions/grant",
            json={
                "target_type": "user",
                "target_id": str(uuid.uuid4()),
                "object_type": "document",
                "object_id": str(uuid.uuid4()),
                "permission": "READ",
            },
        )
        assert resp.status_code == 200
        fake_service.grant_permission.assert_awaited()

    def test_revoke_endpoint(self, api_client):
        client, fake_service = api_client
        resp = client.post(
            "/api/v1/permissions/revoke",
            json={
                "target_type": "group",
                "target_id": str(uuid.uuid4()),
                "object_type": "file_type",
                "object_key": "PDF",
            },
        )
        assert resp.status_code == 200
        fake_service.revoke_permission.assert_awaited()

    def test_list_endpoint(self, api_client):
        client, fake_service = api_client
        user_id = uuid.uuid4()
        resp = client.get(
            "/api/v1/permissions/list",
            params={"target_type": "user", "target_id": str(user_id)},
        )
        assert resp.status_code == 200
        fake_service.list_permissions.assert_awaited()

    def test_check_document_endpoint(self, api_client):
        client, fake_service = api_client
        doc_id = uuid.uuid4()
        resp = client.get(f"/api/v1/permissions/check/document/{doc_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["object_type"] == "document"
        assert data["permission"] == "READ"
        fake_service.check_document_permission.assert_awaited()


class TestPermissionServiceBatch:
    async def test_grant_permissions_batch_success(self, permission_service, fake_db):
        user_id = uuid.uuid4()
        doc_id_1 = uuid.uuid4()
        doc_id_2 = uuid.uuid4()

        permission_service.group_service.get_user_groups = AsyncMock(return_value=[])
        fake_db.begin = MagicMock(return_value=AsyncMockContextManager())

        items = [
            PermissionGrantRequest(
                target_type="user",
                target_id=user_id,
                object_type="document",
                object_id=doc_id_1,
                permission="READ",
            ),
            PermissionGrantRequest(
                target_type="user",
                target_id=user_id,
                object_type="document",
                object_id=doc_id_2,
                permission="WRITE",
            ),
        ]

        results = await permission_service.grant_permissions_batch(items)
        assert len(results) == 2
        fake_db.begin.assert_called_once()

    async def test_grant_permissions_batch_rollback_on_failure(self, permission_service, fake_db):
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        async def failing_grant(*args, **kwargs):
            raise RuntimeError("grant failed")

        permission_service.grant_permission = AsyncMock(side_effect=failing_grant)
        fake_db.begin = MagicMock(return_value=AsyncMockContextManager())

        items = [
            PermissionGrantRequest(
                target_type="user",
                target_id=user_id,
                object_type="document",
                object_id=doc_id,
                permission="READ",
            ),
        ]

        with pytest.raises(ValidationException):
            await permission_service.grant_permissions_batch(items)

    async def test_revoke_permissions_batch_success(self, permission_service, fake_db):
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        permission_service.revoke_permission = AsyncMock(return_value=1)
        fake_db.begin = MagicMock(return_value=AsyncMockContextManager())

        items = [
            PermissionRevokeRequest(
                target_type="user",
                target_id=user_id,
                object_type="document",
                object_id=doc_id,
            ),
        ]

        deleted_counts = await permission_service.revoke_permissions_batch(items)
        assert deleted_counts == [1]
        permission_service.revoke_permission.assert_awaited_once()
        fake_db.begin.assert_called_once()


class TestPermissionServiceValidation:
    async def test_validate_detects_document_read_vs_none_conflict(self, permission_service, fake_db):
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        permission_service.list_permissions = AsyncMock(
            return_value=[
                UnifiedPermissionInfo(
                    id=uuid.uuid4(),
                    target_type="user",
                    target_id=str(user_id),
                    object_type="document",
                    object_id=str(doc_id),
                    object_key=None,
                    permission="READ",
                ),
                UnifiedPermissionInfo(
                    id=uuid.uuid4(),
                    target_type="user",
                    target_id=str(user_id),
                    object_type="document",
                    object_id=str(doc_id),
                    object_key=None,
                    permission="NONE",
                ),
            ]
        )
        permission_service.group_service.get_user_groups = AsyncMock(return_value=[])

        result = await permission_service.validate_permission_inheritance("user", user_id)
        assert isinstance(result, PermissionValidationResponse)
        assert result.valid is False
        assert len(result.conflicts) == 1
        assert result.conflicts[0]["object_type"] == "document"
        assert "READ" in result.conflicts[0]["permissions"]
        assert "NONE" in result.conflicts[0]["permissions"]

    async def test_validate_detects_user_group_conflict(self, permission_service, fake_db):
        user_id = uuid.uuid4()
        group_id = uuid.uuid4()
        doc_id = uuid.uuid4()

        group = MagicMock()
        group.id = group_id

        async def mock_list_permissions(t_type, t_id):
            if t_type == "user" and t_id == user_id:
                return [
                    UnifiedPermissionInfo(
                        id=uuid.uuid4(),
                        target_type="user",
                        target_id=str(user_id),
                        object_type="document",
                        object_id=str(doc_id),
                        object_key=None,
                        permission="READ",
                    ),
                ]
            if t_type == "group" and t_id == group_id:
                return [
                    UnifiedPermissionInfo(
                        id=uuid.uuid4(),
                        target_type="group",
                        target_id=str(group_id),
                        object_type="document",
                        object_id=str(doc_id),
                        object_key=None,
                        permission="DENY",
                    ),
                ]
            return []

        permission_service.list_permissions = AsyncMock(side_effect=mock_list_permissions)
        permission_service.group_service.get_user_groups = AsyncMock(return_value=[group])

        result = await permission_service.validate_permission_inheritance("user", user_id)
        assert result.valid is False
        assert any(c["object_id"] == str(doc_id) for c in result.conflicts)


class TestPermissionApiBatchEndpoints:
    @pytest.fixture
    def api_client(self):
        from fastapi import FastAPI
        from app.api.v1.permissions import router as permissions_router, get_permission_service
        from app.api.v1.auth import get_current_user
        from app.schemas.user import UserResponse

        app = FastAPI()
        app.include_router(permissions_router, prefix="/api/v1")

        user_id = uuid.uuid4()
        app.dependency_overrides[get_current_user] = lambda: UserResponse(
            id=user_id,
            username="alice",
            email="alice@example.com",
            display_name="Alice",
            department="Engineering",
            security_level="L2",
            status="active",
            is_active=True,
        )

        fake_service = AsyncMock()
        fake_perm = MagicMock()
        fake_perm.id = uuid.uuid4()
        fake_service.grant_permissions_batch = AsyncMock(return_value=[fake_perm])
        fake_service.revoke_permissions_batch = AsyncMock(return_value=[1, 1])
        fake_service.validate_permission_inheritance = AsyncMock(
            return_value=PermissionValidationResponse(valid=True, conflicts=[])
        )
        app.dependency_overrides[get_permission_service] = lambda: fake_service

        with TestClient(app) as client:
            yield client, fake_service

    def test_batch_grant_endpoint(self, api_client):
        client, fake_service = api_client
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        resp = client.post(
            "/api/v1/permissions/batch-grant",
            json={
                "items": [
                    {
                        "target_type": "user",
                        "target_id": str(user_id),
                        "object_type": "document",
                        "object_id": str(doc_id),
                        "permission": "READ",
                    }
                ]
            },
        )
        assert resp.status_code == 200
        fake_service.grant_permissions_batch.assert_awaited()

    def test_batch_revoke_endpoint(self, api_client):
        client, fake_service = api_client
        user_id = uuid.uuid4()
        doc_id = uuid.uuid4()
        resp = client.post(
            "/api/v1/permissions/batch-revoke",
            json={
                "items": [
                    {
                        "target_type": "user",
                        "target_id": str(user_id),
                        "object_type": "document",
                        "object_id": str(doc_id),
                    }
                ]
            },
        )
        assert resp.status_code == 200
        fake_service.revoke_permissions_batch.assert_awaited()

    def test_validate_endpoint(self, api_client):
        client, fake_service = api_client
        user_id = uuid.uuid4()
        resp = client.get(
            "/api/v1/permissions/validate",
            params={"target_type": "user", "target_id": str(user_id)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        fake_service.validate_permission_inheritance.assert_awaited()
