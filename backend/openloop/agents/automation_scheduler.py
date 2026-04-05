"""Automation Scheduler — background asyncio loop that fires due cron automations.

Runs every 60 seconds.
- Uses lane-based concurrency manager (automation lane cap: 3).
- Does NOT yield to interactive conversations — lanes are independent.
- On startup, detects missed runs and creates notifications for each.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from contract.enums import AutomationTriggerType, BackgroundTaskRunType, BackgroundTaskStatus, NotificationType, SOURCE_TYPE_GMAIL, SOURCE_TYPE_GOOGLE_CALENDAR
from croniter import croniter

from backend.openloop.agents import concurrency_manager
from backend.openloop.database import SessionLocal
from backend.openloop.db.models import Agent, BackgroundTask, DataSource, Notification
from backend.openloop.services import automation_service, notification_service

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_last_integration_sync: datetime | None = None
_INTEGRATION_SYNC_INTERVAL = timedelta(minutes=15)


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

        # --- Heartbeat evaluation ---
        await _evaluate_heartbeats(db, now_naive)

        # --- Integration syncs (calendar, email) — every 15 minutes ---
        await _run_integration_syncs(db)

        # --- Expire stale approvals ---
        await _expire_stale_approvals(db)
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


async def _run_integration_syncs(db) -> None:
    """Run integration syncs (calendar, email) — called from _tick every 15 minutes."""
    global _last_integration_sync

    now = datetime.now(UTC).replace(tzinfo=None)
    if _last_integration_sync and (now - _last_integration_sync) < _INTEGRATION_SYNC_INTERVAL:
        return  # Not yet time

    _last_integration_sync = now

    # Calendar sync
    try:
        from backend.openloop.services import calendar_integration_service

        # Find calendar data source
        calendar_ds = (
            db.query(DataSource)
            .filter(DataSource.source_type == SOURCE_TYPE_GOOGLE_CALENDAR, DataSource.space_id.is_(None))
            .first()
        )
        if calendar_ds:
            result = calendar_integration_service.sync_events(db, calendar_ds.id)
            logger.info(
                "Calendar sync: +%d -%d ~%d",
                result["added"],
                result["removed"],
                result["updated"],
            )
    except Exception as exc:
        logger.error("Calendar integration sync failed: %s", exc, exc_info=True)

    # Email sync
    try:
        from backend.openloop.services import email_integration_service

        email_ds = (
            db.query(DataSource)
            .filter(DataSource.source_type == SOURCE_TYPE_GMAIL, DataSource.space_id.is_(None))
            .first()
        )
        if email_ds:
            result = email_integration_service.sync_inbox(db, email_ds.id)
            logger.info("Email sync: +%d ~%d", result["added"], result["updated"])
    except Exception as exc:
        logger.error("Email integration sync failed: %s", exc, exc_info=True)


async def _evaluate_heartbeats(db, now_naive: datetime) -> None:
    """Check all heartbeat-enabled agents and fire those whose cron is due."""
    agents = (
        db.query(Agent)
        .filter(
            Agent.heartbeat_enabled == True,  # noqa: E712
            Agent.heartbeat_cron.isnot(None),
            Agent.status == "active",
        )
        .all()
    )

    for agent in agents:
        try:
            if not _is_heartbeat_due(db, agent, now_naive):
                continue
        except Exception:
            logger.warning(
                "Invalid heartbeat cron for agent '%s': %s",
                agent.name,
                agent.heartbeat_cron,
            )
            continue

        # Check automation lane concurrency before firing
        if not concurrency_manager.acquire_slot(db, "automation"):
            logger.debug("Automation lane full — skipping heartbeat for '%s'", agent.name)
            break

        logger.info("Firing heartbeat for agent '%s' (id=%s)", agent.name, agent.id)
        try:
            await _fire_heartbeat(db, agent)
        except Exception:
            logger.error("Failed to fire heartbeat for agent '%s'", agent.name, exc_info=True)


def _is_heartbeat_due(db, agent: Agent, now_naive: datetime) -> bool:
    """Return True if the agent's heartbeat cron is due.

    Uses the most recent BackgroundTask with run_type=heartbeat for that agent
    as the last-run reference. Computes the cron interval (via two consecutive
    get_next calls from the last run) and checks whether at least one full
    interval has elapsed, preventing double-fire when heartbeats run between
    cron boundaries.
    """
    last_heartbeat = (
        db.query(BackgroundTask)
        .filter(
            BackgroundTask.agent_id == agent.id,
            BackgroundTask.run_type == BackgroundTaskRunType.HEARTBEAT,
        )
        .order_by(BackgroundTask.created_at.desc())
        .first()
    )

    if last_heartbeat is None:
        return True  # Never run before — always due

    ref = last_heartbeat.created_at.replace(tzinfo=None)

    # Compute the cron interval from the last run reference point
    cron_iter = croniter(agent.heartbeat_cron, ref)
    next1 = cron_iter.get_next(datetime)
    next2 = cron_iter.get_next(datetime)
    interval = (next2 - next1).total_seconds()

    # Due if at least one full cron interval has elapsed since the last run
    return (now_naive - ref).total_seconds() >= interval


async def _fire_heartbeat(db, agent: Agent) -> None:
    """Build the heartbeat survey prompt and delegate to agent_runner."""
    from backend.openloop.agents import agent_runner

    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    survey_prompt = (
        f"HEARTBEAT — {now_str}\n\n"
        "You have been woken for a periodic check-in.\n"
        "Review the current state of your spaces. Consider:\n"
        "- Are there overdue items that need attention?\n"
        "- Has anything changed since your last check-in?\n"
        "- Are there items you've been assigned that are stale?\n"
        "- Is there anything the user should know about?\n\n"
        "If nothing needs attention, respond with HEARTBEAT_OK.\n"
        "If something needs action and is within your permissions, handle it.\n"
        "If something needs the user's attention, create a notification."
    )

    # Use the agent's first bound space, or None for system agents
    space_id = agent.spaces[0].id if agent.spaces else None

    await agent_runner.delegate_background(
        db,
        agent_id=agent.id,
        instruction=survey_prompt,
        space_id=space_id,
        run_type=BackgroundTaskRunType.HEARTBEAT,
    )


async def _expire_stale_approvals(db) -> None:
    """Expire stale approvals and inject steering for tasks still running."""
    from backend.openloop.agents import agent_runner
    from backend.openloop.services import approval_service

    expired_approvals = approval_service.expire_stale(db)
    if not expired_approvals:
        return

    logger.info("Expired %d stale approval(s)", len(expired_approvals))

    # Inject steering for expired approvals where task is still running
    for entry in expired_approvals:
        task = db.query(BackgroundTask).filter(BackgroundTask.id == entry.background_task_id).first()
        if task and task.status in ("running", "paused") and task.conversation_id:
            try:
                await agent_runner.steer(
                    task.conversation_id,
                    f"Approval expired for: {entry.action_type}. "
                    "No user response within timeout. Skip this action and continue with remaining work.",
                )
            except Exception as e:
                logger.warning("Failed to steer for expired approval %s: %s", entry.id, e)

    # Create notification for expired approvals
    notification_service.create_notification(
        db,
        type=NotificationType.SYSTEM,
        title="Approvals expired",
        body=f"{len(expired_approvals)} approval(s) expired without response.",
    )


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
