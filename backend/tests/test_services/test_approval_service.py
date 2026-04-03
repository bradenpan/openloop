"""Tests for approval_service — approval queue CRUD and lifecycle."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.openloop.db.models import ApprovalQueue, BackgroundTask
from backend.openloop.services import agent_service, approval_service, space_service
from contract.enums import ApprovalStatus, BackgroundTaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(db: Session, name: str = "ApprovalTestAgent") -> str:
    agent = agent_service.create_agent(db, name=name)
    return agent.id


def _make_background_task(db: Session, agent_id: str) -> str:
    space = space_service.create_space(db, name="ApprovalSpace", template="project")
    task = BackgroundTask(
        agent_id=agent_id,
        instruction="test task",
        status=BackgroundTaskStatus.RUNNING,
        space_id=space.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task.id


def _make_approval(
    db: Session,
    agent_id: str,
    background_task_id: str,
    action_type: str = "execute:bash",
    reason: str = "Needs shell access",
) -> ApprovalQueue:
    return approval_service.create_approval(
        db,
        background_task_id=background_task_id,
        agent_id=agent_id,
        action_type=action_type,
        action_detail={"tool_name": "Bash", "command": "ls"},
        reason=reason,
    )


# ---------------------------------------------------------------------------
# create_approval
# ---------------------------------------------------------------------------


def test_create_approval_creates_entry(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)

    entry = approval_service.create_approval(
        db_session,
        background_task_id=task_id,
        agent_id=agent_id,
        action_type="execute:bash",
        action_detail={"tool_name": "Bash", "command": "rm -rf /tmp/old"},
        reason="Need to clean temp files",
    )

    assert entry.id is not None
    assert entry.background_task_id == task_id
    assert entry.agent_id == agent_id
    assert entry.action_type == "execute:bash"
    assert entry.action_detail == {"tool_name": "Bash", "command": "rm -rf /tmp/old"}
    assert entry.reason == "Need to clean temp files"
    assert entry.status == ApprovalStatus.PENDING
    assert entry.resolved_at is None
    assert entry.resolved_by is None
    assert entry.created_at is not None


def test_create_approval_increments_queued_count(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)

    # Initially 0
    task = db_session.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
    assert task.queued_approvals_count == 0

    _make_approval(db_session, agent_id, task_id)

    db_session.refresh(task)
    assert task.queued_approvals_count == 1

    _make_approval(db_session, agent_id, task_id, action_type="create:file")

    db_session.refresh(task)
    assert task.queued_approvals_count == 2


# ---------------------------------------------------------------------------
# resolve_approval
# ---------------------------------------------------------------------------


def test_resolve_approval_sets_status_and_resolved_at(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    entry = _make_approval(db_session, agent_id, task_id)

    resolved = approval_service.resolve_approval(
        db_session, entry.id, status=ApprovalStatus.APPROVED
    )

    assert resolved.status == ApprovalStatus.APPROVED
    assert resolved.resolved_at is not None
    assert resolved.resolved_by == "user"


def test_resolve_approval_decrements_queued_count(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    entry = _make_approval(db_session, agent_id, task_id)

    task = db_session.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
    assert task.queued_approvals_count == 1

    approval_service.resolve_approval(
        db_session, entry.id, status=ApprovalStatus.DENIED
    )

    db_session.refresh(task)
    assert task.queued_approvals_count == 0


def test_resolve_approval_denied(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    entry = _make_approval(db_session, agent_id, task_id)

    resolved = approval_service.resolve_approval(
        db_session, entry.id, status=ApprovalStatus.DENIED, resolved_by="admin"
    )

    assert resolved.status == ApprovalStatus.DENIED
    assert resolved.resolved_by == "admin"


def test_resolve_approval_not_found(db_session: Session):
    import pytest
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        approval_service.resolve_approval(
            db_session, "nonexistent-id", status=ApprovalStatus.APPROVED
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# batch_resolve
# ---------------------------------------------------------------------------


def test_batch_resolve_multiple(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)

    entry1 = _make_approval(db_session, agent_id, task_id, action_type="execute:bash")
    entry2 = _make_approval(db_session, agent_id, task_id, action_type="create:file")
    entry3 = _make_approval(db_session, agent_id, task_id, action_type="edit:config")

    task = db_session.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
    assert task.queued_approvals_count == 3

    resolved = approval_service.batch_resolve(
        db_session,
        [entry1.id, entry2.id],
        status=ApprovalStatus.APPROVED,
    )

    assert len(resolved) == 2
    assert all(r.status == ApprovalStatus.APPROVED for r in resolved)
    assert all(r.resolved_at is not None for r in resolved)

    db_session.refresh(task)
    assert task.queued_approvals_count == 1  # Only entry3 still pending


def test_batch_resolve_skips_nonexistent(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    entry = _make_approval(db_session, agent_id, task_id)

    resolved = approval_service.batch_resolve(
        db_session,
        [entry.id, "nonexistent-id"],
        status=ApprovalStatus.DENIED,
    )

    assert len(resolved) == 1
    assert resolved[0].id == entry.id


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------


def test_list_pending_returns_pending_only(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)

    _make_approval(db_session, agent_id, task_id, action_type="a")
    entry2 = _make_approval(db_session, agent_id, task_id, action_type="b")
    _make_approval(db_session, agent_id, task_id, action_type="c")

    # Resolve one
    approval_service.resolve_approval(
        db_session, entry2.id, status=ApprovalStatus.APPROVED
    )

    pending = approval_service.list_pending(db_session)
    assert len(pending) == 2
    assert all(p.status == ApprovalStatus.PENDING for p in pending)


def test_list_pending_filter_by_agent_id(db_session: Session):
    agent1 = _make_agent(db_session, "Agent1")
    agent2 = _make_agent(db_session, "Agent2")
    task1 = _make_background_task(db_session, agent1)
    # Need a different space name for agent2
    space2 = space_service.create_space(db_session, name="ApprovalSpace2", template="project")
    task2 = BackgroundTask(
        agent_id=agent2,
        instruction="test task 2",
        status=BackgroundTaskStatus.RUNNING,
        space_id=space2.id,
    )
    db_session.add(task2)
    db_session.commit()
    db_session.refresh(task2)

    _make_approval(db_session, agent1, task1)
    _make_approval(db_session, agent2, task2.id)

    pending = approval_service.list_pending(db_session, agent_id=agent1)
    assert len(pending) == 1
    assert pending[0].agent_id == agent1


def test_list_pending_filter_by_background_task_id(db_session: Session):
    agent_id = _make_agent(db_session)
    task1 = _make_background_task(db_session, agent_id)
    # Create second task with different space
    space2 = space_service.create_space(db_session, name="ApprovalSpace3", template="project")
    task2 = BackgroundTask(
        agent_id=agent_id,
        instruction="test task 2",
        status=BackgroundTaskStatus.RUNNING,
        space_id=space2.id,
    )
    db_session.add(task2)
    db_session.commit()
    db_session.refresh(task2)

    _make_approval(db_session, agent_id, task1)
    _make_approval(db_session, agent_id, task2.id)

    pending = approval_service.list_pending(db_session, background_task_id=task1)
    assert len(pending) == 1
    assert pending[0].background_task_id == task1


# ---------------------------------------------------------------------------
# expire_stale
# ---------------------------------------------------------------------------


def test_expire_stale_expires_old_entries(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)

    # Create an entry and manually backdate it
    entry = _make_approval(db_session, agent_id, task_id)
    entry.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
    db_session.commit()

    # Create a fresh entry that should NOT be expired
    fresh = _make_approval(db_session, agent_id, task_id, action_type="fresh")

    expired = approval_service.expire_stale(db_session, default_hours=24)
    assert len(expired) == 1

    db_session.refresh(entry)
    assert entry.status == ApprovalStatus.EXPIRED
    assert entry.resolved_by == "system"
    assert entry.resolved_at is not None

    db_session.refresh(fresh)
    assert fresh.status == ApprovalStatus.PENDING


def test_expire_stale_decrements_queued_count(db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)

    entry = _make_approval(db_session, agent_id, task_id)
    entry.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
    db_session.commit()

    task = db_session.query(BackgroundTask).filter(BackgroundTask.id == task_id).first()
    assert task.queued_approvals_count == 1

    approval_service.expire_stale(db_session, default_hours=24)

    db_session.refresh(task)
    assert task.queued_approvals_count == 0


def test_expire_stale_no_entries(db_session: Session):
    expired = approval_service.expire_stale(db_session, default_hours=24)
    assert len(expired) == 0
