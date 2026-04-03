"""API routes for the approval queue."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas.approvals import (
    ApprovalBatchResolveRequest,
    ApprovalQueueResponse,
    ApprovalResolveRequest,
)
from backend.openloop.database import get_db
from backend.openloop.db.models import BackgroundTask
from backend.openloop.services import approval_service, audit_service
from contract.enums import ApprovalStatus

logger = logging.getLogger(__name__)

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
async def resolve_approval(
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

    # Steering: notify the agent about approval resolution
    task = db.query(BackgroundTask).filter(BackgroundTask.id == entry.background_task_id).first()
    if task and task.status in ("running", "paused") and task.conversation_id:
        from backend.openloop.agents import agent_runner

        if entry.status == ApprovalStatus.APPROVED:
            await agent_runner.steer(
                task.conversation_id,
                f"Approval granted for: {entry.action_type}. "
                "You may now retry this action.",
            )
        elif entry.status == ApprovalStatus.DENIED:
            await agent_runner.steer(
                task.conversation_id,
                f"Approval denied for: {entry.action_type}. "
                "Skip it and continue with remaining work.",
            )
            # Audit log for denied approval
            audit_service.log_action(
                db,
                agent_id=entry.agent_id,
                action=f"approval_denied:{entry.action_type}",
                background_task_id=entry.background_task_id,
                tool_name="approval_queue",
                input_summary=f"Denied by {entry.resolved_by}",
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
