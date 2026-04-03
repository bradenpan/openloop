"""Pydantic schemas for the approval queue."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from contract.enums import ApprovalStatus

__all__ = [
    "ApprovalQueueResponse",
    "ApprovalResolveRequest",
    "ApprovalBatchResolveRequest",
]


class ApprovalQueueResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    background_task_id: str
    agent_id: str
    action_type: str
    action_detail: dict | None
    reason: str | None
    status: str
    resolved_at: datetime | None
    resolved_by: str | None
    created_at: datetime


class ApprovalResolveRequest(BaseModel):
    status: ApprovalStatus  # approved or denied
    resolved_by: str | None = "user"


class ApprovalBatchResolveRequest(BaseModel):
    approval_ids: list[str]
    status: ApprovalStatus  # approved or denied
    resolved_by: str | None = "user"
