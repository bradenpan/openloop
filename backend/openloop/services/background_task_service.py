from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import BackgroundTask


def create_background_task(
    db: Session,
    *,
    agent_id: str,
    instruction: str,
    space_id: str | None = None,
    item_id: str | None = None,
    conversation_id: str | None = None,
    status: str = "running",
) -> BackgroundTask:
    """Create a background task record."""
    task = BackgroundTask(
        agent_id=agent_id,
        instruction=instruction,
        space_id=space_id,
        item_id=item_id,
        conversation_id=conversation_id,
        status=status,
        started_at=datetime.now(UTC),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_background_task(db: Session, task_id: str) -> BackgroundTask:
    """Get a background task by ID, or 404."""
    task = db.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Background task not found")
    return task


def update_background_task(db: Session, task_id: str, **kwargs) -> BackgroundTask:
    """Update background task fields."""
    task = get_background_task(db, task_id)
    updatable = {"status", "result_summary", "error", "completed_at"}
    for field, value in kwargs.items():
        if field in updatable:
            setattr(task, field, value)
    db.commit()
    db.refresh(task)
    return task


def list_background_tasks(
    db: Session,
    *,
    status: str | None = None,
    agent_id: str | None = None,
) -> list[BackgroundTask]:
    """List background tasks with optional filters."""
    query = db.query(BackgroundTask)
    if status is not None:
        query = query.filter(BackgroundTask.status == status)
    if agent_id is not None:
        query = query.filter(BackgroundTask.agent_id == agent_id)
    return query.order_by(BackgroundTask.started_at.desc()).all()
