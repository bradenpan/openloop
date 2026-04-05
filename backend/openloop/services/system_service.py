"""System service — kill switch and system state management.

Stateless module with plain functions. Every function receives db: Session.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from contract.enums import BackgroundTaskStatus, NotificationType
from backend.openloop.db.models import BackgroundTask, Conversation, SystemState
from backend.openloop.services import notification_service

SYSTEM_PAUSED_KEY = "system_paused"


def is_paused(db: Session) -> bool:
    """Quick check: is the system currently paused?"""
    row = db.query(SystemState).filter(SystemState.key == SYSTEM_PAUSED_KEY).first()
    if row is None:
        return False
    return bool(row.value)


def get_status(db: Session) -> dict:
    """Return system status: paused flag and count of active sessions."""
    paused = is_paused(db)

    # Count active interactive sessions (conversations with SDK session)
    active_interactive = (
        db.query(Conversation)
        .filter(
            Conversation.status == "active",
            Conversation.sdk_session_id.isnot(None),
        )
        .count()
    )

    # Count running background tasks
    active_background = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.status == BackgroundTaskStatus.RUNNING)
        .count()
    )

    return {
        "paused": paused,
        "active_sessions": active_interactive + active_background,
    }


def emergency_stop(db: Session) -> dict:
    """Activate the kill switch: pause system and mark all running background tasks as interrupted.

    This is a cooperative kill switch — running SDK query() calls continue until
    their current turn completes, at which point the turn-boundary check in
    agent_runner sees the paused flag and stops. New work is blocked immediately.

    Returns a summary of what was stopped.
    """
    # Set the paused flag
    row = db.query(SystemState).filter(SystemState.key == SYSTEM_PAUSED_KEY).first()
    if row is None:
        row = SystemState(key=SYSTEM_PAUSED_KEY, value=True)
        db.add(row)
    else:
        row.value = True
        row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.flush()

    # Interrupt all running background tasks
    running_tasks = (
        db.query(BackgroundTask)
        .filter(BackgroundTask.status == BackgroundTaskStatus.RUNNING)
        .all()
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    stopped_ids = []
    for task in running_tasks:
        task.status = BackgroundTaskStatus.INTERRUPTED
        task.error = "Emergency stop activated"
        task.completed_at = now
        stopped_ids.append(task.id)

    db.commit()

    # Create summary notification
    if stopped_ids:
        body = (
            f"Emergency stop activated. {len(stopped_ids)} background task(s) interrupted: "
            + ", ".join(stopped_ids[:10])
        )
        if len(stopped_ids) > 10:
            body += f" (and {len(stopped_ids) - 10} more)"
    else:
        body = "Emergency stop activated. No background tasks were running."

    notification_service.create_notification(
        db,
        type=NotificationType.EMERGENCY_STOP,
        title="Emergency stop activated",
        body=body,
    )

    return {
        "paused": True,
        "tasks_interrupted": len(stopped_ids),
        "interrupted_task_ids": stopped_ids,
    }


def resume(db: Session) -> dict:
    """Clear the pause flag, re-enabling system operation."""
    row = db.query(SystemState).filter(SystemState.key == SYSTEM_PAUSED_KEY).first()
    if row is None:
        # Wasn't paused — no-op
        return {"paused": False}

    row.value = False
    row.updated_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()

    notification_service.create_notification(
        db,
        type=NotificationType.SYSTEM,
        title="System resumed",
        body="Emergency stop cleared. Background work re-enabled.",
    )

    return {"paused": False}
