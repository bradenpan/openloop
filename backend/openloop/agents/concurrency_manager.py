"""Concurrency Manager — lane-isolated slot management for agent sessions.

Each workload type gets its own lane with an independent cap.
Background lanes (autonomous, automation, subagent) also share a hard
total-background cap to prevent resource exhaustion.

Slot tracking is DB-based (not in-memory counters) so it survives restarts.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.openloop.db.models import AutomationRun, BackgroundTask, Conversation
from contract.enums import BackgroundTaskStatus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lane definitions: name -> max concurrent sessions
# ---------------------------------------------------------------------------

LANE_CAPS: dict[str, int] = {
    "interactive": 5,
    "autonomous": 2,
    "automation": 3,
    "subagent": 8,
}

# Hard cap across all background lanes (autonomous + automation + subagent)
MAX_TOTAL_BACKGROUND = 8

BACKGROUND_LANES = {"autonomous", "automation", "subagent"}


# ---------------------------------------------------------------------------
# DB-based counting
# ---------------------------------------------------------------------------


def _count_interactive(db: Session) -> int:
    """Count active interactive conversations (those with an SDK session)."""
    return (
        db.query(Conversation)
        .filter(
            Conversation.status == "active",
            Conversation.sdk_session_id.isnot(None),
        )
        .count()
    )


def _count_automation(db: Session) -> int:
    """Count running automation runs."""
    return (
        db.query(AutomationRun)
        .filter(AutomationRun.status == BackgroundTaskStatus.RUNNING)
        .count()
    )


def _count_subagent(db: Session) -> int:
    """Count running background tasks that are sub-agent delegations (have a parent_task_id)."""
    return (
        db.query(BackgroundTask)
        .filter(
            BackgroundTask.status == BackgroundTaskStatus.RUNNING,
            BackgroundTask.parent_task_id.isnot(None),
        )
        .count()
    )


def _count_autonomous(db: Session) -> int:
    """Count running background tasks that are autonomous (no parent, no automation)."""
    return (
        db.query(BackgroundTask)
        .filter(
            BackgroundTask.status == BackgroundTaskStatus.RUNNING,
            BackgroundTask.parent_task_id.is_(None),
            BackgroundTask.automation_id.is_(None),
        )
        .count()
    )


_LANE_COUNTERS = {
    "interactive": _count_interactive,
    "autonomous": _count_autonomous,
    "automation": _count_automation,
    "subagent": _count_subagent,
}


def _count_total_background(db: Session) -> int:
    """Count all running background tasks (regardless of type)."""
    return (
        db.query(BackgroundTask)
        .filter(BackgroundTask.status == BackgroundTaskStatus.RUNNING)
        .count()
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def acquire_slot(db: Session, lane: str) -> bool:
    """Try to acquire a concurrency slot in the given lane.

    Returns True if the slot was acquired (caller may proceed).
    Returns False if the lane is full or the total background cap is reached.

    This is non-blocking and DB-based — no in-memory state to leak.
    """
    if lane not in LANE_CAPS:
        logger.error("Unknown concurrency lane: %s", lane)
        return False

    # Check lane-specific cap
    counter = _LANE_COUNTERS[lane]
    current = counter(db)
    cap = LANE_CAPS[lane]

    if current >= cap:
        logger.debug(
            "Lane '%s' full: %d/%d",
            lane, current, cap,
        )
        return False

    # For background lanes, also enforce the total background cap
    if lane in BACKGROUND_LANES:
        total_bg = _count_total_background(db)
        if total_bg >= MAX_TOTAL_BACKGROUND:
            logger.debug(
                "Total background cap reached: %d/%d (lane '%s' request denied)",
                total_bg, MAX_TOTAL_BACKGROUND, lane,
            )
            return False

    return True


def release_slot(lane: str) -> None:
    """Release a concurrency slot.

    This is a no-op because slot tracking is DB-based: sessions are released
    when their corresponding DB records transition out of 'running'/'active'.
    Kept as a public API for symmetry with acquire_slot.
    """
    pass


def get_lane_status(db: Session) -> dict:
    """Return current and max counts for all lanes, plus total background info.

    Returns::

        {
            "lanes": {
                "interactive": {"current": 2, "max": 5},
                "autonomous": {"current": 0, "max": 2},
                "automation": {"current": 1, "max": 3},
                "subagent": {"current": 3, "max": 8},
            },
            "total_background": {"current": 4, "max": 8},
        }
    """
    lanes = {}
    for lane_name, cap in LANE_CAPS.items():
        counter = _LANE_COUNTERS[lane_name]
        lanes[lane_name] = {
            "current": counter(db),
            "max": cap,
        }

    total_bg = _count_total_background(db)

    return {
        "lanes": lanes,
        "total_background": {"current": total_bg, "max": MAX_TOTAL_BACKGROUND},
    }
