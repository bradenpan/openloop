from datetime import UTC, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, background_task_service, space_service


def _make_agent(db: Session, name: str = "BG Agent"):
    return agent_service.create_agent(db, name=name)


def _make_space(db: Session, name: str = "BG Space"):
    return space_service.create_space(db, name=name, template="simple")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_background_task(db_session: Session):
    agent = _make_agent(db_session)
    task = background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="Do something"
    )
    assert task.agent_id == agent.id
    assert task.instruction == "Do something"
    assert task.status == "running"
    assert task.id is not None
    assert task.started_at is not None


def test_create_background_task_with_space(db_session: Session):
    agent = _make_agent(db_session)
    space = _make_space(db_session)
    task = background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="Task", space_id=space.id
    )
    assert task.space_id == space.id


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_background_task(db_session: Session):
    agent = _make_agent(db_session)
    task = background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="GetMe"
    )
    fetched = background_task_service.get_background_task(db_session, task.id)
    assert fetched.id == task.id
    assert fetched.instruction == "GetMe"


def test_get_background_task_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        background_task_service.get_background_task(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_background_tasks_empty(db_session: Session):
    result = background_task_service.list_background_tasks(db_session)
    assert result == []


def test_list_background_tasks_with_data(db_session: Session):
    agent = _make_agent(db_session)
    background_task_service.create_background_task(db_session, agent_id=agent.id, instruction="A")
    background_task_service.create_background_task(db_session, agent_id=agent.id, instruction="B")
    result = background_task_service.list_background_tasks(db_session)
    assert len(result) == 2


def test_list_background_tasks_filter_by_status(db_session: Session):
    agent = _make_agent(db_session)
    t1 = background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="Running"
    )
    background_task_service.update_background_task(db_session, t1.id, status="completed")
    background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="Still Running"
    )
    running = background_task_service.list_background_tasks(db_session, status="running")
    assert len(running) == 1
    assert running[0].instruction == "Still Running"


def test_list_background_tasks_filter_by_agent(db_session: Session):
    a1 = _make_agent(db_session, name="Agent1")
    a2 = _make_agent(db_session, name="Agent2")
    background_task_service.create_background_task(db_session, agent_id=a1.id, instruction="T1")
    background_task_service.create_background_task(db_session, agent_id=a2.id, instruction="T2")
    result = background_task_service.list_background_tasks(db_session, agent_id=a1.id)
    assert len(result) == 1
    assert result[0].instruction == "T1"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_background_task(db_session: Session):
    agent = _make_agent(db_session)
    task = background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="Update me"
    )
    now = datetime.now(UTC)
    updated = background_task_service.update_background_task(
        db_session,
        task.id,
        status="completed",
        result_summary="Done!",
        completed_at=now,
    )
    assert updated.status == "completed"
    assert updated.result_summary == "Done!"
    assert updated.completed_at is not None


def test_update_background_task_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        background_task_service.update_background_task(db_session, "nonexistent", status="failed")
    assert exc_info.value.status_code == 404
