"""Email API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = [
    "EmailMessageResponse",
    "EmailLabelRequest",
    "DraftCreateRequest",
    "DraftResponse",
    "EmailSyncResponse",
    "EmailStatsResponse",
    "EmailAuthStatusResponse",
    "EmailSetupRequest",
    "EmailReplyRequest",
]


class EmailMessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    gmail_message_id: str | None
    gmail_thread_id: str | None
    subject: str | None
    from_address: str | None
    from_name: str | None
    to_addresses: list | None
    cc_addresses: list | None
    snippet: str | None
    body: str | None = None
    labels: list[str] | None
    is_unread: bool
    received_at: datetime
    gmail_link: str | None
    synced_at: datetime | None


class EmailLabelRequest(BaseModel):
    add_labels: list[str] | None = None
    remove_labels: list[str] | None = None


class DraftCreateRequest(BaseModel):
    to: str
    subject: str
    body: str
    cc: str | None = None
    bcc: str | None = None
    reply_to: str | None = None


class DraftResponse(BaseModel):
    draft_id: str
    message: dict | None = None


class EmailSyncResponse(BaseModel):
    added: int
    updated: int


class EmailStatsResponse(BaseModel):
    unread_count: int
    by_label: dict
    oldest_unread: datetime | None


class EmailAuthStatusResponse(BaseModel):
    authenticated: bool


class EmailSetupRequest(BaseModel):
    triage_labels: list[str] | None = None


class EmailReplyRequest(BaseModel):
    body: str
