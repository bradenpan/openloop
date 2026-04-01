"""Tests for automation_scheduler helper functions and DB interactions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.openloop.agents.automation_scheduler import (
    _count_running_automations,
    _is_due,
)
from backend.openloop.db.models import Agent, AutomationRun
from backend.openloop.services import agent_service, automation_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(db: Session, name: str = "SchedAgent") -> Agent:
    return agent_service.create_agent(db, name=name)


def _make_cron_automation(
    db: Session,
    *,
    agent_id: str,
    name: str = "Cron Auto",
    cron_expression: str = "0 * * * *",  # hourly
    enabled: bool = True,
):
    return automation_service.create_automation(
        db,
        name=name,
        agent_id=agent_id,
        instruction="Scheduled task.",
        trigger_type="cron",
        cron_expression=cron_expression,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# _is_due — cron matching logic
# ---------------------------------------------------------------------------


def test_is_due_overdue_returns_true(db_session: Session):
    """An automation with last_run_at older than one cron interval is due."""
    agent = _make_agent(db_session)
    auto = _make_cron_automation(
        db_session, agent_id=agent.id, cron_expression="0 * * * *"
    )
    # Set last_run_at to 2 hours ago
    auto.last_run_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()

    now_naive = datetime.now(UTC).replace(tzinfo=None)
    assert _is_due(auto, now_naive) is True


def test_is_due_recent_run_returns_false(db_session: Session):
    """An automation that ran just 30 seconds ago (hourly cron) is not yet due."""
    agent = _make_agent(db_session)
    auto = _make_cron_automation(
        db_session, agent_id=agent.id, cron_expression="0 * * * *"
    )
    # last_run_at is 30 seconds ago — next run is ~59.5 minutes from now
    auto.last_run_at = datetime.now(UTC) - timedelta(seconds=30)
    db_session.commit()

    now_naive = datetime.now(UTC).replace(tzinfo=None)
    assert _is_due(auto, now_naive) is False


def test_is_due_never_run_returns_true(db_session: Session):
    """An automation that has never run (last_run_at=None) is treated as due,
    since the first scheduled time after year 2000 has long passed."""
    agent = _make_agent(db_session)
    auto = _make_cron_automation(
        db_session, agent_id=agent.id, cron_expression="0 * * * *"
    )
    assert auto.last_run_at is None

    now_naive = datetime.now(UTC).replace(tzinfo=None)
    assert _is_due(auto, now_naive) is True


def test_is_due_future_cron_expression_not_due(db_session: Session):
    """If we use a daily cron that ran just a moment ago, it should not be due yet."""
    agent = _make_agent(db_session)
    auto = _make_cron_automation(
        db_session,
        agent_id=agent.id,
        # Daily at midnight
        cron_expression="0 0 * * *",
    )
    # Simulate it ran very recently (e.g., 5 minutes ago at the scheduled time)
    auto.last_run_at = datetime.now(UTC) - timedelta(minutes=5)
    db_session.commit()

    now_naive = datetime.now(UTC).replace(tzinfo=None)
    assert _is_due(auto, now_naive) is False


# ---------------------------------------------------------------------------
# Missed-run detection (via get_missed_runs)
# ---------------------------------------------------------------------------


def test_missed_run_detection_overdue_hourly(db_session: Session):
    """An enabled hourly cron automation with last_run_at 2 hours ago is in get_missed_runs."""
    agent = _make_agent(db_session, name="MissedAgent")
    auto = _make_cron_automation(
        db_session,
        agent_id=agent.id,
        name="Missed Hourly",
        cron_expression="0 * * * *",
        enabled=True,
    )
    auto.last_run_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()

    missed = automation_service.get_missed_runs(db_session)
    assert any(m.id == auto.id for m in missed)


def test_missed_run_detection_disabled_not_returned(db_session: Session):
    """Disabled automations are excluded from missed-run detection."""
    agent = _make_agent(db_session, name="DisabledAgent")
    auto = _make_cron_automation(
        db_session,
        agent_id=agent.id,
        name="Disabled Hourly",
        cron_expression="0 * * * *",
        enabled=False,
    )
    auto.last_run_at = datetime.now(UTC) - timedelta(hours=2)
    db_session.commit()

    missed = automation_service.get_missed_runs(db_session)
    assert not any(m.id == auto.id for m in missed)


# ---------------------------------------------------------------------------
# Concurrency limit — _count_running_automations
# ---------------------------------------------------------------------------


def test_count_running_automations_zero_when_none(db_session: Session):
    """With no runs in the DB, running count is 0."""
    count = _count_running_automations(db_session)
    assert count == 0


def test_count_running_automations_counts_only_running(db_session: Session):
    """Only runs with status='running' count toward the concurrency limit."""
    agent = _make_agent(db_session, name="ConcAgent")
    auto = _make_cron_automation(db_session, agent_id=agent.id, name="Concurrent Auto")

    run1 = automation_service.create_run(db_session, automation_id=auto.id)
    run2 = automation_service.create_run(db_session, automation_id=auto.id)
    run3 = automation_service.create_run(db_session, automation_id=auto.id)

    # Complete two of them
    automation_service.complete_run(db_session, run1.id, status="success")
    automation_service.complete_run(db_session, run2.id, status="failed")
    # run3 remains "running"

    count = _count_running_automations(db_session)
    assert count == 1


def test_count_running_automations_multiple_running(db_session: Session):
    """Counts running runs across multiple automations."""
    agent = _make_agent(db_session, name="MultiAgent")
    auto1 = _make_cron_automation(db_session, agent_id=agent.id, name="Auto1")
    auto2 = _make_cron_automation(db_session, agent_id=agent.id, name="Auto2")

    automation_service.create_run(db_session, automation_id=auto1.id)
    automation_service.create_run(db_session, automation_id=auto2.id)

    count = _count_running_automations(db_session)
    assert count == 2


def test_count_running_does_not_exceed_after_completion(db_session: Session):
    """Running count drops to 0 after all runs are completed."""
    agent = _make_agent(db_session, name="FinalAgent")
    auto = _make_cron_automation(db_session, agent_id=agent.id, name="Final Auto")

    run = automation_service.create_run(db_session, automation_id=auto.id)
    assert _count_running_automations(db_session) == 1

    automation_service.complete_run(db_session, run.id, status="success")
    assert _count_running_automations(db_session) == 0
