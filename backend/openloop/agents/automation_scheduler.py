"""Automation Scheduler — background asyncio loop that fires due cron automations.

Runs every 60 seconds.
- Uses lane-based concurrency manager (automation lane cap: 3).
- Does NOT yield to interactive conversations — lanes are independent.
- On startup, detects missed runs and creates notifications for each.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from contract.enums import AutomationTriggerType, BackgroundTaskStatus, NotificationType
from croniter import croniter

from backend.openloop.agents import concurrency_manager
from backend.openloop.database import SessionLocal
from backend.openloop.db.models import Notification
from backend.openloop.services import automation_service, notification_service

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None


async def _run_scheduler() -> None:
    """Main scheduler loop — checks due automations every 60 seconds."""
    # Run missed-run detection on startup before entering the loop
    await _check_missed_runs()

    while True:
        await asyncio.sleep(60)
        try:
            await _tick()
        except Exception:
            logger.error("Automation scheduler tick failed", exc_info=True)


async def _check_missed_runs() -> None:
    """On startup, detect automations that missed runs while the server was down
    and create a notification for each."""
    db = SessionLocal()
    try:
        missed = automation_service.get_missed_runs(db)
        for automation in missed:
            # Check for existing unread missed-run notification
            existing = db.query(Notification).filter(
                Notification.automation_id == automation.id,
                Notification.type == NotificationType.AUTOMATION_MISSED,
                Notification.is_read == False,  # noqa: E712
            ).first()
            if existing:
                continue

            # Compute expected run time for the notification body
            expected_time = _get_expected_run_time(automation)
            notification_service.create_notification(
                db,
                type=NotificationType.AUTOMATION_MISSED,
                title=f"Automation missed: {automation.name}",
                body=(
                    f"{automation.name} was scheduled to run at {expected_time} "
                    f"but the server was down. Run now?"
                ),
                automation_id=automation.id,
            )
            logger.warning("Missed automation '%s' (expected: %s)", automation.name, expected_time)
    except Exception:
        logger.error("Missed-run detection failed", exc_info=True)
    finally:
        db.close()


def _get_expected_run_time(automation) -> str:
    """Compute the expected run time for a missed automation (human-readable)."""
    try:
        if automation.last_run_at is None:
            return "startup (never run)"
        last_naive = automation.last_run_at.replace(tzinfo=None)
        cron = croniter(automation.cron_expression, last_naive)
        next_run = cron.get_next(datetime)
        return next_run.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        return "unknown"


async def _tick() -> None:
    """Single scheduler tick — evaluate all enabled cron automations."""
    db = SessionLocal()
    try:
        # Kill switch guard (Phase 8.4) — skip all automations while paused
        from backend.openloop.services import system_service

        if system_service.is_paused(db):
            logger.debug("System paused — skipping automation cycle")
            return

        # Check automation lane concurrency via the lane-based manager
        if not concurrency_manager.acquire_slot(db, "automation"):
            logger.debug("Automation lane full — skipping cycle")
            return

        # Get enabled cron automations
        all_automations = automation_service.list_automations(db, enabled=True, limit=200)
        now_naive = datetime.now(UTC).replace(tzinfo=None)

        for automation in all_automations:
            if automation.trigger_type != AutomationTriggerType.CRON or not automation.cron_expression:
                continue

            try:
                is_due = _is_due(automation, now_naive)
            except Exception:
                logger.warning(
                    "Invalid cron expression for automation '%s': %s",
                    automation.name,
                    automation.cron_expression,
                )
                continue

            if not is_due:
                continue

            # Re-check concurrency limit before each trigger
            if not concurrency_manager.acquire_slot(db, "automation"):
                logger.debug("Automation lane full mid-cycle — stopping")
                break

            logger.info("Triggering automation '%s' (id=%s)", automation.name, automation.id)
            try:
                await automation_service.trigger_automation(db, automation.id)
            except Exception:
                logger.error("Failed to trigger automation '%s'", automation.name, exc_info=True)
    finally:
        db.close()


def _count_running_automations(db) -> int:
    """Count how many automation runs are currently in 'running' status across all automations."""
    from backend.openloop.db.models import AutomationRun

    return db.query(AutomationRun).filter(AutomationRun.status == BackgroundTaskStatus.RUNNING).count()


def _is_due(automation, now_naive: datetime) -> bool:
    """Return True if this cron automation is due to run right now.

    An automation is due if the next scheduled time after its last_run_at (or epoch
    if never run) is <= now.
    """
    if automation.last_run_at is None:
        # Never run — treat "start of time" as the reference point
        ref = datetime(2000, 1, 1)
    else:
        ref = automation.last_run_at.replace(tzinfo=None)

    cron = croniter(automation.cron_expression, ref)
    next_run = cron.get_next(datetime)
    return next_run <= now_naive


def start_automation_scheduler() -> None:
    """Start the automation scheduler loop. Called on app startup."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_run_scheduler())
        _scheduler_task.add_done_callback(
            lambda t: logger.error("Automation scheduler exited: %s", t.exception())
            if not t.cancelled() and t.exception() else None
        )
        logger.info("Automation scheduler started (60s interval)")


def stop_automation_scheduler() -> None:
    """Stop the scheduler loop. Called on app shutdown."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        logger.info("Automation scheduler stopped")
