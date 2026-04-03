"""API routes for the approval queue."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas.approvals import (
    ApprovalBatchResolveRequest,
    ApprovalQueueResponse,
    ApprovalResolveRequest,
)
from backend.openloop.database import get_db
from backend.openloop.services import approval_service

router = APIRouter(prefix="/api/v1/approval-queue", tags=["approval-queue"])


@router.get("", response_model=list[ApprovalQueueResponse])
def list_pending(
    agent_id: str | None = Query(None),
    background_task_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[ApprovalQueueResponse]:
    entries = approval_service.list_pending(
        db,
        agent_id=agent_id,
        background_task_id=background_task_id,
        limit=limit,
        offset=offset,
    )
    return [ApprovalQueueResponse.model_validate(e) for e in entries]


@router.post("/{approval_id}/resolve", response_model=ApprovalQueueResponse)
def resolve_approval(
    approval_id: str,
    body: ApprovalResolveRequest,
    db: Session = Depends(get_db),
) -> ApprovalQueueResponse:
    entry = approval_service.resolve_approval(
        db,
        approval_id,
        status=body.status,
        resolved_by=body.resolved_by or "user",
    )
    return ApprovalQueueResponse.model_validate(entry)


@router.post("/batch-resolve", response_model=list[ApprovalQueueResponse])
def batch_resolve(
    body: ApprovalBatchResolveRequest,
    db: Session = Depends(get_db),
) -> list[ApprovalQueueResponse]:
    entries = approval_service.batch_resolve(
        db,
        body.approval_ids,
        status=body.status,
        resolved_by=body.resolved_by or "user",
    )
    return [ApprovalQueueResponse.model_validate(e) for e in entries]
