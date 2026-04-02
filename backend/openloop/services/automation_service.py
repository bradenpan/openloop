"""Automation service — CRUD and run management for automations."""

import logging
from datetime import UTC, datetime

from contract.enums import AutomationTriggerType, BackgroundTaskStatus
from croniter import croniter
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Automation, AutomationRun

logger = logging.getLogger(__name__)


def create_automation(
    db: Session,
    *,
    name: str,
    description: str | None = None,
    agent_id: str,
    instruction: str,
    trigger_type: str,
    cron_expression: str | None = None,
    space_id: str | None = None,
    model_override: str | None = None,
    enabled: bool = True,
) -> Automation:
    """Create a new automation."""
    automation = Automation(
        name=name,
        description=description,
        agent_id=agent_id,
        instruction=instruction,
        trigger_type=trigger_type,
        cron_expression=cron_expression,
        space_id=space_id,
        model_override=model_override,
        enabled=enabled,
    )
    db.add(automation)
    db.commit()
    db.refresh(automation)
    return automation


def get_automation(db: Session, automation_id: str) -> Automation:
    """Get an automation by ID, or 404."""
    automation = db.query(Automation).filter(Automation.id == automation_id).first()
    if not automation:
        raise HTTPException(status_code=404, detail="Automation not found")
    return automation


def list_automations(
    db: Session,
    *,
    enabled: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Automation]:
    """List automations with optional enabled filter."""
    query = db.query(Automation)
    if enabled is not None:
        query = query.filter(Automation.enabled == enabled)
    return query.order_by(Automation.created_at.desc()).offset(offset).limit(limit).all()


def update_automation(db: Session, automation_id: str, **kwargs) -> Automation:
    """Update automation fields. Uses exclude_unset pattern — only set fields are updated."""
    automation = get_automation(db, automation_id)
    updatable = {
        "name",
        "description",
        "agent_id",
        "instruction",
        "trigger_type",
        "cron_expression",
        "space_id",
        "model_override",
        "enabled",
    }
    for field, value in kwargs.items():
        if field in updatable:
            setattr(automation, field, value)
    db.commit()
    db.refresh(automation)
    return automation


def delete_automation(db: Session, automation_id: str) -> None:
    """Delete an automation."""
    automation = get_automation(db, automation_id)
    db.delete(automation)
    db.commit()


async def trigger_automation(db: Session, automation_id: str) -> "AutomationRun":
    """Manually trigger an automation. Creates an AutomationRun and fires as a background task.

    Returns the AutomationRun record (status='running').
    """
    # Import lazily to avoid circular imports (same pattern as task_monitor)
    import asyncio

    from backend.openloop.agents import session_manager

    automation = get_automation(db, automation_id)

    # Create the run record first
    run = create_run(db, automation_id=automation_id)

    # Extract scalar values before defining _fire() to avoid detached-object risk
    agent_id = automation.agent_id
    instruction = automation.instruction
    space_id = automation.space_id
    model_override = automation.model_override
    run_id = run.id

    # Fire the background task asynchronously
    async def _fire() -> None:
        from backend.openloop.database import SessionLocal

        task_db = SessionLocal()
        try:
            task_id = await session_manager.delegate_background(
                task_db,
                agent_id=agent_id,
                instruction=instruction,
                space_id=space_id,
                automation_run_id=run_id,
                model_override=model_override,
            )
            # Link the background task to the run
            _run = task_db.query(AutomationRun).filter(AutomationRun.id == run_id).first()
            if _run:
                _run.background_task_id = task_id
                task_db.commit()
        except Exception as exc:
            logger.error("Automation %s fire failed: %s", automation_id, exc, exc_info=True)
            task_db2 = SessionLocal()
            try:
                complete_run(
                    task_db2,
                    run_id=run_id,
                    status=BackgroundTaskStatus.FAILED,
                    error="Failed to launch background task",
                )
            finally:
                task_db2.close()
        finally:
            task_db.close()

    asyncio.create_task(_fire())

    return run


def list_runs(
    db: Session,
    automation_id: str,
    *,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[AutomationRun]:
    """List runs for an automation, most recent first."""
    query = db.query(AutomationRun).filter(AutomationRun.automation_id == automation_id)
    if status is not None:
        query = query.filter(AutomationRun.status == status)
    return query.order_by(AutomationRun.started_at.desc()).offset(offset).limit(limit).all()


def create_run(
    db: Session,
    automation_id: str,
    *,
    background_task_id: str | None = None,
) -> AutomationRun:
    """Create an AutomationRun record with status='running'."""
    run = AutomationRun(
        automation_id=automation_id,
        background_task_id=background_task_id,
        status=BackgroundTaskStatus.RUNNING,
        started_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def complete_run(
    db: Session,
    run_id: str,
    *,
    status: str,
    result_summary: str | None = None,
    error: str | None = None,
) -> AutomationRun:
    """Mark a run as complete, update its parent automation's last_run fields."""
    run = db.query(AutomationRun).filter(AutomationRun.id == run_id).first()
    if not run:
        raise ValueError(f"AutomationRun {run_id} not found")

    now = datetime.now(UTC)
    run.status = status
    run.result_summary = result_summary
    run.error = error
    run.completed_at = now

    # Update parent automation
    automation = db.query(Automation).filter(Automation.id == run.automation_id).first()
    if automation:
        automation.last_run_at = now
        automation.last_run_status = status

    db.commit()
    db.refresh(run)
    return run


def get_missed_runs(db: Session) -> list[Automation]:
    """Return enabled cron automations that missed their last scheduled run.

    An automation is considered missed if:
    - trigger_type == 'cron'
    - cron_expression is set and valid
    - last_run_at is None (never run), or the next scheduled time after last_run_at
      has already passed.
    """
    now = datetime.now(UTC)
    # Make naive for croniter (croniter works with naive datetimes)
    now_naive = now.replace(tzinfo=None)

    automations = (
        db.query(Automation)
        .filter(Automation.enabled == True)  # noqa: E712
        .filter(Automation.trigger_type == AutomationTriggerType.CRON)
        .filter(Automation.cron_expression.isnot(None))
        .all()
    )

    missed = []
    for automation in automations:
        try:
            croniter(automation.cron_expression)
        except Exception:
            # Invalid cron expression — skip
            continue

        if automation.last_run_at is None:
            # Never run — check if first scheduled time has passed since creation
            created_naive = automation.created_at.replace(tzinfo=None)
            cron_from_created = croniter(automation.cron_expression, created_naive)
            first_run = cron_from_created.get_next(datetime)
            if first_run < now_naive:
                missed.append(automation)
        else:
            # Compute next expected run after last_run_at
            last_naive = automation.last_run_at.replace(tzinfo=None)
            cron_from_last = croniter(automation.cron_expression, last_naive)
            next_run = cron_from_last.get_next(datetime)
            if next_run < now_naive:
                missed.append(automation)

    return missed
