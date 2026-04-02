"""Unit tests for automation_service."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent
from backend.openloop.services import agent_service, automation_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(db: Session, name: str = "TestAgent") -> Agent:
    return agent_service.create_agent(db, name=name)


def _make_automation(
    db: Session,
    *,
    agent_id: str,
    name: str = "Daily Report",
    trigger_type: str = "event",
    cron_expression: str | None = None,
    enabled: bool = True,
) -> automation_service.Automation:
    return automation_service.create_automation(
        db,
        name=name,
        agent_id=agent_id,
        instruction="Run the daily report.",
        trigger_type=trigger_type,
        cron_expression=cron_expression,
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# create_automation
# ---------------------------------------------------------------------------


def test_create_automation_correct_fields(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id, name="My Auto")
    assert auto.name == "My Auto"
    assert auto.agent_id == agent.id
    assert auto.instruction == "Run the daily report."
    assert auto.trigger_type == "event"
    assert auto.id is not None


def test_create_automation_defaults_enabled_true(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    assert auto.enabled is True


def test_create_automation_disabled(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id, enabled=False)
    assert auto.enabled is False


def test_create_automation_with_cron(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(
        db_session,
        agent_id=agent.id,
        trigger_type="cron",
        cron_expression="0 9 * * *",
    )
    assert auto.trigger_type == "cron"
    assert auto.cron_expression == "0 9 * * *"


# ---------------------------------------------------------------------------
# get_automation
# ---------------------------------------------------------------------------


def test_get_automation(db_session: Session):
    agent = _make_agent(db_session)
    created = _make_automation(db_session, agent_id=agent.id)
    fetched = automation_service.get_automation(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.name == created.name


def test_get_automation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        automation_service.get_automation(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# list_automations
# ---------------------------------------------------------------------------


def test_list_automations_returns_all(db_session: Session):
    agent = _make_agent(db_session)
    _make_automation(db_session, agent_id=agent.id, name="A")
    _make_automation(db_session, agent_id=agent.id, name="B")
    result = automation_service.list_automations(db_session)
    assert len(result) == 2


def test_list_automations_empty(db_session: Session):
    result = automation_service.list_automations(db_session)
    assert result == []


def test_list_automations_filter_enabled_true(db_session: Session):
    agent = _make_agent(db_session)
    _make_automation(db_session, agent_id=agent.id, name="Enabled", enabled=True)
    _make_automation(db_session, agent_id=agent.id, name="Disabled", enabled=False)
    result = automation_service.list_automations(db_session, enabled=True)
    assert len(result) == 1
    assert result[0].name == "Enabled"


def test_list_automations_filter_enabled_false(db_session: Session):
    agent = _make_agent(db_session)
    _make_automation(db_session, agent_id=agent.id, name="Enabled", enabled=True)
    _make_automation(db_session, agent_id=agent.id, name="Disabled", enabled=False)
    result = automation_service.list_automations(db_session, enabled=False)
    assert len(result) == 1
    assert result[0].name == "Disabled"


# ---------------------------------------------------------------------------
# update_automation
# ---------------------------------------------------------------------------


def test_update_automation_name_only(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(
        db_session, agent_id=agent.id, name="Old Name", trigger_type="event"
    )
    updated = automation_service.update_automation(db_session, auto.id, name="New Name")
    assert updated.name == "New Name"
    # Other fields unchanged
    assert updated.trigger_type == "event"
    assert updated.instruction == "Run the daily report."


def test_update_automation_enabled_toggle(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id, enabled=True)
    updated = automation_service.update_automation(db_session, auto.id, enabled=False)
    assert updated.enabled is False
    assert updated.name == auto.name  # unchanged


def test_update_automation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        automation_service.update_automation(db_session, "nonexistent-id", name="X")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_automation
# ---------------------------------------------------------------------------


def test_delete_automation(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    automation_service.delete_automation(db_session, auto.id)
    with pytest.raises(HTTPException) as exc_info:
        automation_service.get_automation(db_session, auto.id)
    assert exc_info.value.status_code == 404


def test_delete_automation_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        automation_service.delete_automation(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# create_run + complete_run
# ---------------------------------------------------------------------------


def test_create_run_status_running(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    run = automation_service.create_run(db_session, automation_id=auto.id)
    assert run.status == "running"
    assert run.automation_id == auto.id
    assert run.started_at is not None
    assert run.completed_at is None
    assert run.id is not None


def test_complete_run_sets_completed_at(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    run = automation_service.create_run(db_session, automation_id=auto.id)
    completed = automation_service.complete_run(
        db_session, run.id, status="completed", result_summary="Done"
    )
    assert completed.status == "completed"
    assert completed.completed_at is not None
    assert completed.result_summary == "Done"


def test_complete_run_updates_parent_automation(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    run = automation_service.create_run(db_session, automation_id=auto.id)
    automation_service.complete_run(db_session, run.id, status="completed")

    db_session.expire(auto)
    refreshed = automation_service.get_automation(db_session, auto.id)
    assert refreshed.last_run_at is not None
    assert refreshed.last_run_status == "completed"


def test_complete_run_failed_status(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    run = automation_service.create_run(db_session, automation_id=auto.id)
    completed = automation_service.complete_run(
        db_session, run.id, status="failed", error="Something went wrong"
    )
    assert completed.status == "failed"
    assert completed.error == "Something went wrong"


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------


def test_list_runs_returns_runs_for_automation(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    automation_service.create_run(db_session, automation_id=auto.id)
    automation_service.create_run(db_session, automation_id=auto.id)
    runs = automation_service.list_runs(db_session, auto.id)
    assert len(runs) == 2


def test_list_runs_respects_limit(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    for _ in range(5):
        automation_service.create_run(db_session, automation_id=auto.id)
    runs = automation_service.list_runs(db_session, auto.id, limit=2)
    assert len(runs) == 2


def test_list_runs_respects_offset(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    for _ in range(3):
        automation_service.create_run(db_session, automation_id=auto.id)
    all_runs = automation_service.list_runs(db_session, auto.id)
    paged = automation_service.list_runs(db_session, auto.id, limit=2, offset=1)
    assert len(paged) == 2
    assert paged[0].id == all_runs[1].id


def test_list_runs_status_filter(db_session: Session):
    agent = _make_agent(db_session)
    auto = _make_automation(db_session, agent_id=agent.id)
    run1 = automation_service.create_run(db_session, automation_id=auto.id)
    run2 = automation_service.create_run(db_session, automation_id=auto.id)
    automation_service.complete_run(db_session, run1.id, status="completed")
    # run2 is still "running"
    running = automation_service.list_runs(db_session, auto.id, status="running")
    assert len(running) == 1
    assert running[0].id == run2.id


# ---------------------------------------------------------------------------
# get_missed_runs
# ---------------------------------------------------------------------------


def test_get_missed_runs_returns_overdue_automation(db_session: Session):
    """An enabled cron automation whose last_run_at is older than its cron interval
    should appear in get_missed_runs."""
    agent = _make_agent(db_session)
    auto = _make_automation(
        db_session,
        agent_id=agent.id,
        trigger_type="cron",
        cron_expression="0 * * * *",  # hourly
        enabled=True,
    )
    # Simulate last run 2 hours ago
    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
    auto.last_run_at = two_hours_ago
    db_session.commit()

    missed = automation_service.get_missed_runs(db_session)
    assert any(m.id == auto.id for m in missed)


def test_get_missed_runs_excludes_recent_automation(db_session: Session):
    """An automation that ran very recently (within the last minute) should NOT be in
    get_missed_runs."""
    agent = _make_agent(db_session)
    auto = _make_automation(
        db_session,
        agent_id=agent.id,
        trigger_type="cron",
        cron_expression="0 * * * *",  # hourly
        enabled=True,
    )
    # Simulate last run just 30 seconds ago — next run is ~59.5 minutes from now
    just_now = datetime.now(UTC) - timedelta(seconds=30)
    auto.last_run_at = just_now
    db_session.commit()

    missed = automation_service.get_missed_runs(db_session)
    assert not any(m.id == auto.id for m in missed)


def test_get_missed_runs_never_run_is_missed(db_session: Session):
    """An automation that has never run, created more than one cron interval ago, is missed."""
    agent = _make_agent(db_session)
    auto = _make_automation(
        db_session,
        agent_id=agent.id,
        trigger_type="cron",
        cron_expression="0 * * * *",
        enabled=True,
    )
    assert auto.last_run_at is None
    # Simulate that the automation was created 2 hours ago so its first run has passed
    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
    auto.created_at = two_hours_ago
    db_session.commit()

    missed = automation_service.get_missed_runs(db_session)
    assert any(m.id == auto.id for m in missed)


def test_get_missed_runs_excludes_disabled_automations(db_session: Session):
    """Disabled automations should never appear in get_missed_runs, even if overdue."""
    agent = _make_agent(db_session)
    auto = _make_automation(
        db_session,
        agent_id=agent.id,
        trigger_type="cron",
        cron_expression="0 * * * *",
        enabled=False,
    )
    two_hours_ago = datetime.now(UTC) - timedelta(hours=2)
    auto.last_run_at = two_hours_ago
    db_session.commit()

    missed = automation_service.get_missed_runs(db_session)
    assert not any(m.id == auto.id for m in missed)


def test_get_missed_runs_excludes_event_trigger_type(db_session: Session):
    """Event-trigger automations are never scheduled, so they never appear in
    get_missed_runs (which only checks cron automations)."""
    agent = _make_agent(db_session)
    auto = _make_automation(
        db_session,
        agent_id=agent.id,
        trigger_type="event",
        enabled=True,
    )
    missed = automation_service.get_missed_runs(db_session)
    assert not any(m.id == auto.id for m in missed)
