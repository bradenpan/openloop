"""Approval queue service — manages queued approvals for autonomous agents.

When an autonomous agent hits a permission boundary, the action is queued
here instead of blocking. The user can later approve or deny queued actions.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, ApprovalQueue, BackgroundTask
from contract.enums import ApprovalStatus, BackgroundTaskStatus


def create_approval(
    db: Session,
    *,
    background_task_id: str,
    agent_id: str,
    action_type: str,
    action_detail: dict | None = None,
    reason: str | None = None,
) -> ApprovalQueue:
    """Create an approval queue entry with status=pending.

    Also increments queued_approvals_count on the associated BackgroundTask
    and publishes an APPROVAL_QUEUED SSE event.
    """
    entry = ApprovalQueue(
        background_task_id=background_task_id,
        agent_id=agent_id,
        action_type=action_type,
        action_detail=action_detail,
        reason=reason,
        status=ApprovalStatus.PENDING,
    )
    db.add(entry)

    # Increment queued_approvals_count on the background task
    task = db.query(BackgroundTask).filter(BackgroundTask.id == background_task_id).first()
    if task is not None:
        task.queued_approvals_count = (task.queued_approvals_count or 0) + 1

    db.commit()
    db.refresh(entry)

    # Publish SSE event (best-effort, don't fail if event bus unavailable)
    try:
        import asyncio

        from backend.openloop.agents.event_bus import event_bus
        from contract.enums import SSEEventType

        event = {
            "type": SSEEventType.APPROVAL_QUEUED,
            "data": {
                "approval_id": entry.id,
                "background_task_id": background_task_id,
                "agent_id": agent_id,
                "action_type": action_type,
                "reason": reason,
            },
        }
        # Try to publish; if no running event loop, skip
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(event_bus.publish(event))
        except RuntimeError:
            # No running event loop (e.g., in sync test context) — skip
            pass
    except Exception:
        pass

    return entry


def resolve_approval(
    db: Session,
    approval_id: str,
    *,
    status: str,
    resolved_by: str = "user",
) -> ApprovalQueue:
    """Resolve a single approval entry (approved or denied).

    Sets status, resolved_at, resolved_by. Decrements queued_approvals_count
    on the associated BackgroundTask.

    If status is "approved" but the associated BackgroundTask is no longer
    running (not in running/paused), the approval is set to "expired" instead.
    """
    entry = db.query(ApprovalQueue).filter(ApprovalQueue.id == approval_id).first()
    if entry is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Approval not found")

    if entry.status != ApprovalStatus.PENDING:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail="Approval already resolved")

    # Check if task is still running when approving
    task = db.query(BackgroundTask).filter(BackgroundTask.id == entry.background_task_id).first()
    if status == ApprovalStatus.APPROVED and task is not None:
        if task.status not in (
            BackgroundTaskStatus.RUNNING.value,
            BackgroundTaskStatus.PAUSED.value,
        ):
            # Task is no longer running — expire the approval instead
            status = ApprovalStatus.EXPIRED

    entry.status = status
    entry.resolved_at = datetime.now(UTC).replace(tzinfo=None)
    entry.resolved_by = resolved_by

    # Decrement queued_approvals_count on the background task
    if task is not None and (task.queued_approvals_count or 0) > 0:
        task.queued_approvals_count = task.queued_approvals_count - 1

    db.commit()
    db.refresh(entry)
    return entry


def batch_resolve(
    db: Session,
    approval_ids: list[str],
    *,
    status: str,
    resolved_by: str = "user",
) -> list[ApprovalQueue]:
    """Resolve multiple approval entries at once."""
    resolved = []
    for approval_id in approval_ids:
        entry = db.query(ApprovalQueue).filter(ApprovalQueue.id == approval_id).first()
        if entry is None:
            continue
        if entry.status != ApprovalStatus.PENDING:
            continue
        entry.status = status
        entry.resolved_at = datetime.now(UTC).replace(tzinfo=None)
        entry.resolved_by = resolved_by

        # Decrement queued_approvals_count on the background task
        task = db.query(BackgroundTask).filter(BackgroundTask.id == entry.background_task_id).first()
        if task is not None and (task.queued_approvals_count or 0) > 0:
            task.queued_approvals_count = task.queued_approvals_count - 1

        resolved.append(entry)

    db.commit()
    for entry in resolved:
        db.refresh(entry)
    return resolved


def list_pending(
    db: Session,
    *,
    agent_id: str | None = None,
    background_task_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[ApprovalQueue]:
    """List pending approval entries with optional filters."""
    q = db.query(ApprovalQueue).filter(ApprovalQueue.status == ApprovalStatus.PENDING)
    if agent_id is not None:
        q = q.filter(ApprovalQueue.agent_id == agent_id)
    if background_task_id is not None:
        q = q.filter(ApprovalQueue.background_task_id == background_task_id)
    return q.order_by(ApprovalQueue.created_at.desc()).offset(offset).limit(limit).all()


def expire_stale(
    db: Session,
    *,
    default_hours: int = 24,
) -> list[ApprovalQueue]:
    """Find pending approvals past their timeout and expire them.

    Uses per-agent approval_timeout_hours if set, otherwise default_hours.
    Returns the list of expired entries (so callers can handle steering).
    """
    pending = (
        db.query(ApprovalQueue)
        .filter(ApprovalQueue.status == ApprovalStatus.PENDING)
        .all()
    )

    now = datetime.now(UTC).replace(tzinfo=None)
    expired: list[ApprovalQueue] = []

    for entry in pending:
        # Look up per-agent timeout
        agent = db.query(Agent).filter(Agent.id == entry.agent_id).first()
        timeout_hours = (
            agent.approval_timeout_hours
            if agent and agent.approval_timeout_hours
            else default_hours
        )
        cutoff = now - timedelta(hours=timeout_hours)

        if entry.created_at < cutoff:
            entry.status = ApprovalStatus.EXPIRED
            entry.resolved_at = now
            entry.resolved_by = "system"

            # Decrement queued_approvals_count on the background task
            task = db.query(BackgroundTask).filter(BackgroundTask.id == entry.background_task_id).first()
            if task is not None and (task.queued_approvals_count or 0) > 0:
                task.queued_approvals_count = task.queued_approvals_count - 1

            expired.append(entry)

    if expired:
        db.commit()

    return expired
