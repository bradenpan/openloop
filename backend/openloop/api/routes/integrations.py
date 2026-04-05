"""Integration auth management endpoints."""

from fastapi import APIRouter, Query

from backend.openloop.api.schemas.integrations import AuthStatusResponse, AuthUrlResponse
from backend.openloop.services import google_auth

router = APIRouter(prefix="/api/v1/integrations", tags=["integrations"])


@router.get("/auth-status", response_model=AuthStatusResponse)
def get_auth_status() -> AuthStatusResponse:
    """Get current Google OAuth authentication status."""
    status = google_auth.get_auth_status()
    return AuthStatusResponse(**status)


@router.get("/auth-url", response_model=AuthUrlResponse)
def get_auth_url(scopes: str | None = Query(None)) -> AuthUrlResponse:
    """Generate OAuth consent URL. Optionally specify scopes (comma-separated)."""
    scope_list = scopes.split(",") if scopes else None
    url = google_auth.get_auth_url(scope_list)
    return AuthUrlResponse(url=url)
