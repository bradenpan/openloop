"""Schemas for integration auth endpoints."""

from pydantic import BaseModel

__all__ = ["AuthStatusResponse", "AuthUrlResponse"]


class AuthStatusResponse(BaseModel):
    authenticated: bool
    granted_scopes: list[str]
    missing_scopes: list[str]
    has_credentials_file: bool


class AuthUrlResponse(BaseModel):
    url: str
