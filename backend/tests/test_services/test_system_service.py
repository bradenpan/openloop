"""Tests for system_service — kill switch (emergency stop / resume)."""

from sqlalchemy.orm import Session

from backend.openloop.db.models import BackgroundTask, Notification, SystemState
from backend.openloop.services import agent_service, background_task_service, system_service


def _make_agent(db: Session, name: str = "SysAgent"):
    return agent_service.create_agent(db, name=name)


# ---------------------------------------------------------------------------
# is_paused
# ---------------------------------------------------------------------------


def test_is_paused_default_false(db_session: Session):
    """System is not paused when no SystemState row exists."""
    assert system_service.is_paused(db_session) is False


def test_is_paused_after_emergency_stop(db_session: Session):
    _make_agent(db_session)  # needed for notification FK constraints
    system_service.emergency_stop(db_session)
    assert system_service.is_paused(db_session) is True


def test_is_paused_after_resume(db_session: Session):
    system_service.emergency_stop(db_session)
    system_service.resume(db_session)
    assert system_service.is_paused(db_session) is False


# ---------------------------------------------------------------------------
# emergency_stop
# ---------------------------------------------------------------------------


def test_emergency_stop_interrupts_running_tasks(db_session: Session):
    agent = _make_agent(db_session)
    t1 = background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="task1", status="running"
    )
    t2 = background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="task2", status="running"
    )
    # One queued task — should NOT be interrupted
    t3 = background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="task3", status="queued"
    )

    result = system_service.emergency_stop(db_session)

    assert result["paused"] is True
    assert result["tasks_interrupted"] == 2
    assert t1.id in result["interrupted_task_ids"]
    assert t2.id in result["interrupted_task_ids"]
    assert t3.id not in result["interrupted_task_ids"]

    # Verify DB state
    db_session.refresh(t1)
    db_session.refresh(t2)
    db_session.refresh(t3)
    assert t1.status == "interrupted"
    assert t2.status == "interrupted"
    assert t3.status == "queued"  # untouched
    assert t1.error == "Emergency stop activated"


def test_emergency_stop_creates_notification(db_session: Session):
    system_service.emergency_stop(db_session)
    notifications = db_session.query(Notification).all()
    assert len(notifications) == 1
    assert notifications[0].type == "emergency_stop"
    assert "Emergency stop activated" in notifications[0].title


def test_emergency_stop_no_running_tasks(db_session: Session):
    result = system_service.emergency_stop(db_session)
    assert result["tasks_interrupted"] == 0
    assert result["interrupted_task_ids"] == []


def test_emergency_stop_idempotent(db_session: Session):
    system_service.emergency_stop(db_session)
    # Second call should still work
    result = system_service.emergency_stop(db_session)
    assert result["paused"] is True


# ---------------------------------------------------------------------------
# resume
# ---------------------------------------------------------------------------


def test_resume_clears_paused(db_session: Session):
    system_service.emergency_stop(db_session)
    result = system_service.resume(db_session)
    assert result["paused"] is False
    assert system_service.is_paused(db_session) is False


def test_resume_when_not_paused(db_session: Session):
    result = system_service.resume(db_session)
    assert result["paused"] is False


def test_resume_creates_notification(db_session: Session):
    system_service.emergency_stop(db_session)
    system_service.resume(db_session)
    notifications = db_session.query(Notification).filter(
        Notification.type == "system"
    ).all()
    assert len(notifications) == 1
    assert "resumed" in notifications[0].title.lower()


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


def test_get_status_default(db_session: Session):
    status = system_service.get_status(db_session)
    assert status["paused"] is False
    assert status["active_sessions"] == 0


def test_get_status_when_paused(db_session: Session):
    system_service.emergency_stop(db_session)
    status = system_service.get_status(db_session)
    assert status["paused"] is True
