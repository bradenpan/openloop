from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.openloop.db.models import (
    Agent,
    ApprovalQueue,
    BackgroundTask,
    Conversation,
    ConversationMessage,
    Notification,
    SystemState,
)
from backend.openloop.services import summary_service


def _make_agent(db: Session, name: str = "TestAgent") -> Agent:
    agent = Agent(name=name)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _make_conversation(db: Session, agent_id: str) -> Conversation:
    conv = Conversation(agent_id=agent_id, name="test-conv")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _make_task(
    db: Session,
    agent_id: str,
    *,
    goal: str = "Test goal",
    run_type: str = "autonomous",
    status: str = "completed",
    conversation_id: str | None = None,
    task_list: list | None = None,
    completed_count: int = 0,
    total_count: int = 0,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    run_summary: str | None = None,
) -> BackgroundTask:
    task = BackgroundTask(
        agent_id=agent_id,
        instruction="do something",
        goal=goal,
        run_type=run_type,
        status=status,
        conversation_id=conversation_id,
        task_list=task_list,
        completed_count=completed_count,
        total_count=total_count,
        started_at=started_at or datetime.now(UTC),
        completed_at=completed_at,
        run_summary=run_summary,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# generate_run_summary tests
# ---------------------------------------------------------------------------


def test_generate_run_summary_basic(db_session: Session):
    agent = _make_agent(db_session)
    now = datetime.now(UTC)
    task_list = [
        {"title": "Task 1", "status": "completed"},
        {"title": "Task 2", "status": "completed"},
        {"title": "Task 3", "status": "completed"},
        {"title": "Task 4", "status": "completed"},
        {"title": "Task 5", "status": "completed"},
        {"title": "Task 6", "status": "skipped"},
        {"title": "Task 7", "status": "skipped"},
    ]
    task = _make_task(
        db_session,
        agent.id,
        goal="Organize the project files",
        task_list=task_list,
        completed_count=5,
        total_count=7,
        started_at=now - timedelta(minutes=30),
        completed_at=now,
    )

    summary = summary_service.generate_run_summary(db_session, task.id)

    assert "Goal: Organize the project files" in summary
    assert "5/7 items completed" in summary
    assert "completed: 5" in summary
    assert "skipped: 2" in summary
    assert "30m" in summary


def test_summary_includes_token_usage(db_session: Session):
    agent = _make_agent(db_session)
    conv = _make_conversation(db_session, agent.id)

    # Create messages with token counts
    for i in range(3):
        msg = ConversationMessage(
            conversation_id=conv.id,
            role="assistant",
            content=f"response {i}",
            input_tokens=1000,
            output_tokens=500,
        )
        db_session.add(msg)
    db_session.commit()

    task = _make_task(
        db_session,
        agent.id,
        conversation_id=conv.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        completed_at=datetime.now(UTC),
    )

    summary = summary_service.generate_run_summary(db_session, task.id)

    assert "Token usage:" in summary
    assert "3,000 input" in summary
    assert "1,500 output" in summary


def test_summary_includes_approval_counts(db_session: Session):
    agent = _make_agent(db_session)
    task = _make_task(
        db_session,
        agent.id,
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        completed_at=datetime.now(UTC),
    )

    # Create approval entries
    for _ in range(2):
        db_session.add(ApprovalQueue(
            background_task_id=task.id,
            agent_id=agent.id,
            action_type="create_item",
            status="approved",
        ))
    db_session.add(ApprovalQueue(
        background_task_id=task.id,
        agent_id=agent.id,
        action_type="delete_item",
        status="denied",
    ))
    db_session.commit()

    summary = summary_service.generate_run_summary(db_session, task.id)

    assert "Approvals:" in summary
    assert "2 approved" in summary
    assert "1 denied" in summary


def test_summary_stored_on_task(db_session: Session):
    agent = _make_agent(db_session)
    task = _make_task(
        db_session,
        agent.id,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        completed_at=datetime.now(UTC),
    )

    summary_service.generate_run_summary(db_session, task.id)

    # Reload from DB
    db_session.expire_all()
    reloaded = db_session.query(BackgroundTask).filter(BackgroundTask.id == task.id).first()
    assert reloaded is not None
    assert reloaded.run_summary is not None
    assert "Goal: Test goal" in reloaded.run_summary


def test_summary_creates_notification(db_session: Session):
    agent = _make_agent(db_session)
    task = _make_task(
        db_session,
        agent.id,
        goal="Process inbox items",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        completed_at=datetime.now(UTC),
    )

    summary_service.generate_run_summary(db_session, task.id)

    notifs = db_session.query(Notification).filter(
        Notification.type == "task_completed"
    ).all()
    assert len(notifs) == 1
    assert "Process inbox items" in notifs[0].title


# ---------------------------------------------------------------------------
# get_morning_brief tests
# ---------------------------------------------------------------------------


def test_morning_brief_returns_recent_tasks(db_session: Session):
    agent = _make_agent(db_session)
    now = datetime.now(UTC)

    # Set last_seen to 12h ago
    row = SystemState(key="user_last_seen", value=(now - timedelta(hours=12)).isoformat())
    db_session.add(row)
    db_session.commit()

    # Recent task (6h ago) — should be included
    _make_task(
        db_session,
        agent.id,
        goal="Recent task",
        run_summary="Recent summary",
        completed_at=now - timedelta(hours=6),
    )

    # Old task (18h ago) — should be excluded
    _make_task(
        db_session,
        agent.id,
        goal="Old task",
        run_summary="Old summary",
        completed_at=now - timedelta(hours=18),
    )

    brief = summary_service.get_morning_brief(db_session)

    assert len(brief["agents"]) == 1
    runs = brief["agents"][0]["runs"]
    assert len(runs) == 1
    assert runs[0]["goal"] == "Recent task"


def test_morning_brief_empty_when_no_work(db_session: Session):
    now = datetime.now(UTC)

    # Set last_seen to now
    row = SystemState(key="user_last_seen", value=now.isoformat())
    db_session.add(row)
    db_session.commit()

    brief = summary_service.get_morning_brief(db_session)

    assert brief["agents"] == []
    assert brief["pending_approvals_count"] == 0
    assert brief["failed_tasks_count"] == 0


def test_morning_brief_groups_by_agent(db_session: Session):
    agent1 = _make_agent(db_session, name="Agent1")
    agent2 = _make_agent(db_session, name="Agent2")
    now = datetime.now(UTC)

    # Set last_seen to 24h ago
    row = SystemState(key="user_last_seen", value=(now - timedelta(hours=24)).isoformat())
    db_session.add(row)
    db_session.commit()

    _make_task(
        db_session,
        agent1.id,
        goal="Agent1 task",
        run_summary="Summary 1",
        completed_at=now - timedelta(hours=2),
    )
    _make_task(
        db_session,
        agent2.id,
        goal="Agent2 task",
        run_summary="Summary 2",
        completed_at=now - timedelta(hours=1),
    )

    brief = summary_service.get_morning_brief(db_session)

    assert len(brief["agents"]) == 2
    agent_names = {a["agent_name"] for a in brief["agents"]}
    assert agent_names == {"Agent1", "Agent2"}
