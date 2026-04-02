"""Memory Lifecycle Scheduler — background asyncio loop for memory maintenance.

Runs every 60 seconds, tracks daily/monthly jobs:
- Daily: auto-archive superseded facts (90+ days old)
- Monthly: consolidate each space's memory + create notification
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from contract.enums import NotificationType

from backend.openloop.database import SessionLocal
from backend.openloop.services import memory_service, notification_service, space_service

logger = logging.getLogger(__name__)

_scheduler_task: asyncio.Task | None = None
_last_daily_run: datetime | None = None
_last_monthly_run: datetime | None = None


async def _run_scheduler() -> None:
    """Main lifecycle loop — checks for due maintenance jobs every 60 seconds."""
    while True:
        await asyncio.sleep(60)
        try:
            await _tick()
        except Exception:
            logger.error("Lifecycle scheduler tick failed", exc_info=True)


async def _tick() -> None:
    """Single scheduler tick — evaluate daily and monthly lifecycle jobs."""
    global _last_daily_run, _last_monthly_run

    now = datetime.now(UTC)

    # Daily job: auto-archive superseded facts
    if _last_daily_run is None or now.date() > _last_daily_run.date():
        await _run_daily(now)
        _last_daily_run = now

    # Monthly job: consolidate each space's memory
    if _last_monthly_run is None or (
        now.year > _last_monthly_run.year
        or (now.year == _last_monthly_run.year and now.month > _last_monthly_run.month)
    ):
        await _run_monthly(now)
        _last_monthly_run = now


async def _run_daily(now: datetime) -> None:
    """Daily maintenance: auto-archive superseded facts."""
    db = SessionLocal()
    try:
        count = memory_service.auto_archive_superseded(db)
        if count > 0:
            logger.info("Lifecycle daily: auto-archived %d superseded facts", count)
    except Exception:
        db.rollback()
        logger.error("Lifecycle daily auto-archive failed", exc_info=True)
    finally:
        db.close()


async def _run_monthly(now: datetime) -> None:
    """Monthly maintenance: consolidate each space's memory."""
    db = SessionLocal()
    try:
        spaces_data = [(s.id, s.name) for s in space_service.list_spaces(db, limit=200)]
    except Exception:
        logger.error("Lifecycle monthly: failed to list spaces", exc_info=True)
        spaces_data = []
    finally:
        db.close()

    # Use a fresh DB session per space to avoid long-lived sessions during LLM calls
    for space_id, space_name in spaces_data:
        space_db = SessionLocal()
        try:
            report = await memory_service.consolidate_space_memory(space_db, space_id)
            total_items = (
                len(report.get("merges") or [])
                + len(report.get("contradictions") or [])
                + len(report.get("stale") or [])
            )
            if total_items > 0:
                notification_service.create_notification(
                    space_db,
                    type=NotificationType.MEMORY_CONSOLIDATION,
                    title=f"Memory review: {space_name}",
                    body=(
                        f"Found {len(report.get('merges') or [])} merge(s), "
                        f"{len(report.get('contradictions') or [])} contradiction(s), "
                        f"{len(report.get('stale') or [])} stale fact(s). "
                        f"Review in space settings."
                    ),
                    space_id=space_id,
                )
                logger.info(
                    "Lifecycle monthly: space '%s' consolidation found %d items",
                    space_name,
                    total_items,
                )
        except Exception:
            space_db.rollback()
            logger.error(
                "Lifecycle monthly: consolidation failed for space '%s'",
                space_name,
                exc_info=True,
            )
        finally:
            space_db.close()


def start_lifecycle_scheduler() -> None:
    """Start the lifecycle scheduler loop. Called on app startup."""
    global _scheduler_task
    if _scheduler_task is None or _scheduler_task.done():
        _scheduler_task = asyncio.create_task(_run_scheduler())
        logger.info("Lifecycle scheduler started (60s interval)")


def stop_lifecycle_scheduler() -> None:
    """Stop the scheduler loop. Called on app shutdown."""
    global _scheduler_task
    if _scheduler_task and not _scheduler_task.done():
        _scheduler_task.cancel()
        logger.info("Lifecycle scheduler stopped")
