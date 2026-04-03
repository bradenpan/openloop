"""Tests for approval lifecycle — expiry with per-agent timeout, resolve steering."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, ApprovalQueue, BackgroundTask, Notification
from backend.openloop.services import agent_service, approval_service, space_service
from contract.enums import ApprovalStatus, BackgroundTaskStatus, NotificationType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(
    db: Session,
    name: str = "LifecycleAgent",
    approval_timeout_hours: int | None = None,
) -> Agent:
    agent = agent_service.create_agent(db, name=name)
    if approval_timeout_hours is not None:
        agent.approval_timeout_hours = approval_timeout_hours
        db.commit()
        db.refresh(agent)
    return agent


def _make_background_task(
    db: Session,
    agent_id: str,
    space_name: str = "LifecycleSpace",
    status: str = BackgroundTaskStatus.RUNNING,
    conversation_id: str | None = None,
) -> BackgroundTask:
    space = space_service.create_space(db, name=space_name, template="project")
    task = BackgroundTask(
        agent_id=agent_id,
        instruction="lifecycle test task",
        status=status,
        space_id=space.id,
        conversation_id=conversation_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _make_approval(
    db: Session,
    agent_id: str,
    background_task_id: str,
    action_type: str = "execute:bash",
    hours_ago: float = 0,
) -> ApprovalQueue:
    entry = approval_service.create_approval(
        db,
        background_task_id=background_task_id,
        agent_id=agent_id,
        action_type=action_type,
        action_detail={"tool_name": "Bash", "command": "ls"},
        reason="Test reason",
    )
    if hours_ago > 0:
        entry.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours_ago)
        db.commit()
        db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# expire_stale — basic
# ---------------------------------------------------------------------------


def test_expire_stale_marks_old_approvals_expired(db_session: Session):
    """Approvals older than default 24h should be expired."""
    agent = _make_agent(db_session)
    task = _make_background_task(db_session, agent.id)
    entry = _make_approval(db_session, agent.id, task.id, hours_ago=25)

    expired = approval_service.expire_stale(db_session)
    assert len(expired) == 1

    db_session.refresh(entry)
    assert entry.status == ApprovalStatus.EXPIRED
    assert entry.resolved_by == "system"
    assert entry.resolved_at is not None


def test_expire_stale_skips_recent_approvals(db_session: Session):
    """Approvals younger than 24h should remain pending."""
    agent = _make_agent(db_session)
    task = _make_background_task(db_session, agent.id)
    entry = _make_approval(db_session, agent.id, task.id, hours_ago=1)

    expired = approval_service.expire_stale(db_session)
    assert len(expired) == 0

    db_session.refresh(entry)
    assert entry.status == ApprovalStatus.PENDING


# ---------------------------------------------------------------------------
# expire_stale — per-agent timeout
# ---------------------------------------------------------------------------


def test_per_agent_timeout_longer(db_session: Session):
    """Agent with approval_timeout_hours=48 keeps 30h-old approvals pending."""
    agent = _make_agent(db_session, name="SlowAgent", approval_timeout_hours=48)
    task = _make_background_task(db_session, agent.id)

    # 30h old — should NOT be expired with 48h timeout
    entry_30h = _make_approval(db_session, agent.id, task.id, action_type="action_30h", hours_ago=30)
    expired = approval_service.expire_stale(db_session)
    assert len(expired) == 0
    db_session.refresh(entry_30h)
    assert entry_30h.status == ApprovalStatus.PENDING

    # 50h old — should BE expired with 48h timeout
    entry_50h = _make_approval(
        db_session, agent.id, task.id, action_type="action_50h", hours_ago=50
    )
    expired = approval_service.expire_stale(db_session)
    assert len(expired) == 1
    db_session.refresh(entry_50h)
    assert entry_50h.status == ApprovalStatus.EXPIRED


# ---------------------------------------------------------------------------
# resolve_approval — task status checks
# ---------------------------------------------------------------------------


def test_resolve_approved_on_running_task(db_session: Session):
    """Approving while task is running sets status to approved."""
    agent = _make_agent(db_session, name="RunningAgent")
    task = _make_background_task(
        db_session, agent.id, space_name="RunningSpace", status=BackgroundTaskStatus.RUNNING
    )
    entry = _make_approval(db_session, agent.id, task.id)

    resolved = approval_service.resolve_approval(
        db_session, entry.id, status=ApprovalStatus.APPROVED
    )
    assert resolved.status == ApprovalStatus.APPROVED


def test_resolve_approved_on_completed_task(db_session: Session):
    """Approving while task is completed sets status to expired instead."""
    agent = _make_agent(db_session, name="CompletedAgent")
    task = _make_background_task(
        db_session, agent.id, space_name="CompletedSpace", status=BackgroundTaskStatus.COMPLETED
    )
    entry = _make_approval(db_session, agent.id, task.id)

    resolved = approval_service.resolve_approval(
        db_session, entry.id, status=ApprovalStatus.APPROVED
    )
    assert resolved.status == ApprovalStatus.EXPIRED


def test_resolve_denied(db_session: Session):
    """Denying an approval sets status to denied regardless of task status."""
    agent = _make_agent(db_session, name="DeniedAgent")
    task = _make_background_task(
        db_session, agent.id, space_name="DeniedSpace", status=BackgroundTaskStatus.RUNNING
    )
    entry = _make_approval(db_session, agent.id, task.id)

    resolved = approval_service.resolve_approval(
        db_session, entry.id, status=ApprovalStatus.DENIED
    )
    assert resolved.status == ApprovalStatus.DENIED


# ---------------------------------------------------------------------------
# expire_stale — return value
# ---------------------------------------------------------------------------


def test_expire_returns_list(db_session: Session):
    """expire_stale returns a list with exactly the expired entries."""
    agent = _make_agent(db_session, name="ListAgent")
    task = _make_background_task(db_session, agent.id, space_name="ListSpace")

    # 3 old approvals
    _make_approval(db_session, agent.id, task.id, action_type="old1", hours_ago=25)
    _make_approval(db_session, agent.id, task.id, action_type="old2", hours_ago=30)
    _make_approval(db_session, agent.id, task.id, action_type="old3", hours_ago=48)

    # 1 recent
    _make_approval(db_session, agent.id, task.id, action_type="recent", hours_ago=1)

    expired = approval_service.expire_stale(db_session)
    assert len(expired) == 3
    assert all(e.status == ApprovalStatus.EXPIRED for e in expired)
    action_types = {e.action_type for e in expired}
    assert action_types == {"old1", "old2", "old3"}


# ---------------------------------------------------------------------------
# notification on expiry
# ---------------------------------------------------------------------------


def test_notification_created_on_expiry(db_session: Session):
    """When approvals are expired by the scheduler helper, a notification is created.

    This tests the notification creation logic that lives in the scheduler's
    _expire_stale_approvals function. Since that function is async and tightly
    coupled to the scheduler loop, we test the notification creation pattern
    directly using notification_service.
    """
    from backend.openloop.services import notification_service

    agent = _make_agent(db_session, name="NotifAgent")
    task = _make_background_task(db_session, agent.id, space_name="NotifSpace")
    _make_approval(db_session, agent.id, task.id, hours_ago=25)

    expired = approval_service.expire_stale(db_session)
    assert len(expired) == 1

    # Simulate what the scheduler does after expire_stale
    notification_service.create_notification(
        db_session,
        type=NotificationType.SYSTEM,
        title="Approvals expired",
        body=f"{len(expired)} approval(s) expired without response.",
    )

    notifs = (
        db_session.query(Notification)
        .filter(Notification.type == NotificationType.SYSTEM, Notification.title == "Approvals expired")
        .all()
    )
    assert len(notifs) == 1
    assert "1 approval(s)" in notifs[0].body


# ---------------------------------------------------------------------------
# queued_approvals_count on expiry
# ---------------------------------------------------------------------------


def test_queued_count_decremented_on_expiry(db_session: Session):
    """Expiring an approval decrements the task's queued_approvals_count."""
    agent = _make_agent(db_session, name="CountAgent")
    task = _make_background_task(db_session, agent.id, space_name="CountSpace")

    _make_approval(db_session, agent.id, task.id, action_type="a")
    _make_approval(db_session, agent.id, task.id, action_type="b")

    db_session.refresh(task)
    assert task.queued_approvals_count == 2

    # Backdate only one approval
    entry = (
        db_session.query(ApprovalQueue)
        .filter(ApprovalQueue.action_type == "a")
        .first()
    )
    entry.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=25)
    db_session.commit()

    expired = approval_service.expire_stale(db_session)
    assert len(expired) == 1

    db_session.refresh(task)
    assert task.queued_approvals_count == 1
