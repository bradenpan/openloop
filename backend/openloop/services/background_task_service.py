from datetime import UTC, datetime, timedelta

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
    parent_task_id: str | None = None,
    automation_id: str | None = None,
    goal: str | None = None,
    time_budget: int | None = None,
    token_budget: int | None = None,
    task_list: list | None = None,
    run_type: str = "task",
    run_summary: str | None = None,
    status: str = "running",
) -> BackgroundTask:
    """Create a background task record."""
    task = BackgroundTask(
        agent_id=agent_id,
        instruction=instruction,
        space_id=space_id,
        item_id=item_id,
        conversation_id=conversation_id,
        parent_task_id=parent_task_id,
        automation_id=automation_id,
        goal=goal,
        time_budget=time_budget,
        token_budget=token_budget,
        task_list=task_list,
        run_type=run_type,
        run_summary=run_summary,
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
    updatable = {"status", "result_summary", "error", "completed_at", "current_step", "total_steps", "step_results", "parent_task_id", "goal", "time_budget", "token_budget", "task_list", "task_list_version", "completed_count", "total_count", "queued_approvals_count", "run_type", "run_summary"}
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
    parent_task_id: str | None = None,
) -> list[BackgroundTask]:
    """List background tasks with optional filters."""
    query = db.query(BackgroundTask)
    if status is not None:
        query = query.filter(BackgroundTask.status == status)
    if agent_id is not None:
        query = query.filter(BackgroundTask.agent_id == agent_id)
    if parent_task_id is not None:
        query = query.filter(BackgroundTask.parent_task_id == parent_task_id)
    return query.order_by(BackgroundTask.created_at.desc()).all()


def list_child_tasks(db: Session, parent_task_id: str) -> list[BackgroundTask]:
    """List child tasks spawned by a parent task."""
    return (
        db.query(BackgroundTask)
        .filter(BackgroundTask.parent_task_id == parent_task_id)
        .order_by(BackgroundTask.created_at.asc())
        .all()
    )


def update_task_progress(
    db: Session,
    task_id: str,
    *,
    current_step: int,
    total_steps: int,
    step_summary: str,
) -> BackgroundTask:
    """Update step progress on a background task.

    Appends the step summary to step_results JSON array.
    """
    task = get_background_task(db, task_id)
    task.current_step = current_step
    task.total_steps = total_steps
    # Reassign the list to trigger SQLAlchemy JSON mutation detection
    results = list(task.step_results or [])
    results.append({"step": current_step, "summary": step_summary, "at": datetime.now(UTC).isoformat()})
    task.step_results = results
    db.commit()
    db.refresh(task)
    return task


def detect_stale_stuck(db: Session) -> list[BackgroundTask]:
    """Find stale (queued >10min) and stuck (running >30min) tasks.

    Returns tasks that need attention.
    """
    now = datetime.now(UTC)
    stale_threshold = now - timedelta(minutes=10)
    stuck_threshold = now - timedelta(minutes=30)

    stale = (
        db.query(BackgroundTask)
        .filter(
            BackgroundTask.status == "queued",
            BackgroundTask.created_at < stale_threshold,
        )
        .all()
    )
    stuck = (
        db.query(BackgroundTask)
        .filter(
            BackgroundTask.status == "running",
            BackgroundTask.started_at < stuck_threshold,
        )
        .all()
    )
    return stale + stuck
