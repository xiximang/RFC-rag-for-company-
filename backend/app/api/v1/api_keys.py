"""API key management endpoints.

All endpoints require JWT authentication. Users can only manage keys they own,
and each key's scopes are constrained by the owner's security level.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.exceptions import AuthenticationException, AuthorizationException
from app.database import get_db
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyResponse
from app.schemas.user import UserResponse
from app.services.api_key_service import ALL_SCOPES, ApiKeyService

router = APIRouter(prefix="/api-keys", tags=["API Keys"])


def _service(db: AsyncSession) -> ApiKeyService:
    return ApiKeyService(db)


@router.post("", response_model=ApiKeyCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    data: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """Create a new API key for the authenticated user."""
    service = _service(db)
    try:
        api_key, plain_key = await service.create_key(
            owner_id=current_user.id,
            name=data.name,
            scopes=data.scopes,
            rate_limit_rpm=data.rate_limit_rpm,
            expires_at=data.expires_at,
        )
    except (AuthenticationException, AuthorizationException) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message)

    response = ApiKeyResponse.model_validate(api_key)
    return ApiKeyCreateResponse(**response.model_dump(), plain_key=plain_key)


@router.get("", response_model=list[ApiKeyResponse])
async def list_api_keys(
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """List API keys owned by the authenticated user."""
    service = _service(db)
    keys = await service.list_keys(current_user.id, include_inactive=include_inactive)
    return [ApiKeyResponse.model_validate(k) for k in keys]


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_api_key(
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: UserResponse = Depends(get_current_user),
):
    """Revoke (deactivate) one of the authenticated user's API keys."""
    service = _service(db)
    revoked = await service.revoke_key(key_id, current_user.id)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    return None


@router.get("/scopes")
async def list_available_scopes(
    current_user: UserResponse = Depends(get_current_user),
):
    """Return the scopes the current user may assign to an API key."""
    allowed = ApiKeyService.scopes_for_level(current_user.security_level)
    return {
        "allowed_scopes": allowed,
        "all_scopes": sorted(ALL_SCOPES),
    }
