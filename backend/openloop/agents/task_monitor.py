"""Task Monitor — background loop detecting stale and stuck tasks.

Runs every 60 seconds. Creates notifications for:
- Stale tasks: queued for >10 minutes
- Stuck tasks: running for >30 minutes

Phase 6's automation scheduler may absorb this loop later.
"""

from __future__ import annotations

import asyncio
import logging

from backend.openloop.database import SessionLocal
from backend.openloop.services import background_task_service, notification_service

logger = logging.getLogger(__name__)

_monitor_task: asyncio.Task | None = None

# Track already-notified task IDs to avoid duplicate notifications
_notified_task_ids: set[str] = set()


async def _check_stale_stuck() -> None:
    """Periodic check for stale/stuck tasks."""
    while True:
        await asyncio.sleep(60)
        try:
            db = SessionLocal()
            try:
                problems = background_task_service.detect_stale_stuck(db)
                for task in problems:
                    if task.id in _notified_task_ids:
                        continue
                    label = "stale" if task.status == "queued" else "stuck"
                    notification_service.create_notification(
                        db,
                        type=f"task_{label}",
                        title=f"Background task {label}",
                        body=f"Task '{task.instruction[:100]}' is {label} ({task.status}).",
                        space_id=task.space_id,
                    )
                    _notified_task_ids.add(task.id)
                    logger.warning("Task %s is %s: %s", task.id, label, task.instruction[:80])

                # Clean up notified set — remove IDs for tasks that are no longer problematic
                if _notified_task_ids:
                    problem_ids = {t.id for t in problems}
                    _notified_task_ids.intersection_update(problem_ids)
            finally:
                db.close()
        except Exception:
            logger.error("Task monitor check failed", exc_info=True)


def start_task_monitor() -> None:
    """Start the stale/stuck detection loop. Called on app startup."""
    global _monitor_task
    if _monitor_task is None or _monitor_task.done():
        _monitor_task = asyncio.create_task(_check_stale_stuck())
        _monitor_task.add_done_callback(
            lambda t: logger.error("Task monitor exited: %s", t.exception())
            if not t.cancelled() and t.exception() else None
        )
        logger.info("Task monitor started (60s interval)")


def stop_task_monitor() -> None:
    """Stop the monitor loop. Called on app shutdown."""
    global _monitor_task
    if _monitor_task and not _monitor_task.done():
        _monitor_task.cancel()
        logger.info("Task monitor stopped")
