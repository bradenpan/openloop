"""Tests for Task 9.1 — schema extensions for autonomous agent operations."""

import uuid

from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, ApprovalQueue, BackgroundTask
from contract.enums import ApprovalStatus, BackgroundTaskRunType, SSEEventType


def _make_agent(db: Session, **overrides) -> Agent:
    """Helper to create a minimal agent."""
    defaults = {
        "id": str(uuid.uuid4()),
        "name": f"test-agent-{uuid.uuid4().hex[:8]}",
    }
    defaults.update(overrides)
    agent = Agent(**defaults)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _make_background_task(db: Session, agent_id: str, **overrides) -> BackgroundTask:
    """Helper to create a minimal background task."""
    defaults = {
        "id": str(uuid.uuid4()),
        "agent_id": agent_id,
        "instruction": "do something",
        "status": "running",
    }
    defaults.update(overrides)
    task = BackgroundTask(**defaults)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---- Enum tests ----


def test_background_task_run_type_enum_values():
    assert BackgroundTaskRunType.TASK == "task"
    assert BackgroundTaskRunType.AUTONOMOUS == "autonomous"
    assert BackgroundTaskRunType.HEARTBEAT == "heartbeat"


def test_approval_status_enum_values():
    assert ApprovalStatus.PENDING == "pending"
    assert ApprovalStatus.APPROVED == "approved"
    assert ApprovalStatus.DENIED == "denied"
    assert ApprovalStatus.EXPIRED == "expired"


def test_sse_event_type_autonomous_constants():
    assert SSEEventType.AUTONOMOUS_PROGRESS == "autonomous_progress"
    assert SSEEventType.APPROVAL_QUEUED == "approval_queued"
    assert SSEEventType.GOAL_COMPLETE == "goal_complete"


# ---- BackgroundTask tests ----


def test_background_task_defaults_to_run_type_task(db_session: Session):
    agent = _make_agent(db_session)
    task = _make_background_task(db_session, agent.id)

    assert task.run_type == "task"
    assert task.task_list is None
    assert task.task_list_version == 0
    assert task.completed_count == 0
    assert task.total_count == 0
    assert task.queued_approvals_count == 0
    assert task.run_summary is None


def test_background_task_autonomous_run_type(db_session: Session):
    agent = _make_agent(db_session)
    task = _make_background_task(
        db_session,
        agent.id,
        run_type="autonomous",
        task_list=[{"step": 1, "description": "research"}, {"step": 2, "description": "write"}],
        total_count=2,
        goal="Write a report",
        run_summary="Initial plan created",
    )

    assert task.run_type == "autonomous"
    assert task.task_list == [{"step": 1, "description": "research"}, {"step": 2, "description": "write"}]
    assert task.total_count == 2
    assert task.completed_count == 0
    assert task.goal == "Write a report"
    assert task.run_summary == "Initial plan created"


def test_background_task_existing_fields_still_work(db_session: Session):
    """Verify goal, time_budget, and token_budget from earlier phases still work."""
    agent = _make_agent(db_session)
    task = _make_background_task(
        db_session,
        agent.id,
        goal="Compile data",
        time_budget=600,
        token_budget=50000,
    )

    assert task.goal == "Compile data"
    assert task.time_budget == 600
    assert task.token_budget == 50000


# ---- Agent tests ----


def test_agent_has_autonomous_fields(db_session: Session):
    agent = _make_agent(db_session)

    assert agent.max_spawn_depth == 1
    assert agent.heartbeat_enabled is False
    assert agent.heartbeat_cron is None


def test_agent_custom_autonomous_fields(db_session: Session):
    agent = _make_agent(
        db_session,
        max_spawn_depth=3,
        heartbeat_enabled=True,
        heartbeat_cron="0 */6 * * *",
    )

    assert agent.max_spawn_depth == 3
    assert agent.heartbeat_enabled is True
    assert agent.heartbeat_cron == "0 */6 * * *"


# ---- ApprovalQueue tests ----


def test_approval_queue_create(db_session: Session):
    agent = _make_agent(db_session)
    task = _make_background_task(db_session, agent.id, run_type="autonomous")

    approval = ApprovalQueue(
        id=str(uuid.uuid4()),
        background_task_id=task.id,
        agent_id=agent.id,
        action_type="file_write",
        action_detail={"tool": "write_file", "path": "/data/report.md"},
        reason="Need to save generated report",
    )
    db_session.add(approval)
    db_session.commit()
    db_session.refresh(approval)

    assert approval.status == "pending"
    assert approval.action_type == "file_write"
    assert approval.action_detail["tool"] == "write_file"
    assert approval.reason == "Need to save generated report"
    assert approval.resolved_at is None
    assert approval.resolved_by is None
    assert approval.created_at is not None


def test_approval_queue_resolve(db_session: Session):
    agent = _make_agent(db_session)
    task = _make_background_task(db_session, agent.id)

    approval = ApprovalQueue(
        id=str(uuid.uuid4()),
        background_task_id=task.id,
        agent_id=agent.id,
        action_type="api_call",
        reason="Fetch external data",
    )
    db_session.add(approval)
    db_session.commit()

    # Resolve it
    from datetime import UTC, datetime

    approval.status = "approved"
    approval.resolved_by = "user"
    approval.resolved_at = datetime.now(UTC)
    db_session.commit()
    db_session.refresh(approval)

    assert approval.status == "approved"
    assert approval.resolved_by == "user"
    assert approval.resolved_at is not None
