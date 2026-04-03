"""Tests for Task 11.1: Crash Recovery for Autonomous Runs.

Tests cover:
- Autonomous tasks with remaining items set to pending_resume
- Autonomous tasks without task list marked failed
- Autonomous tasks with all completed items marked failed
- Autonomous tasks without goal marked failed
- Regular tasks still marked failed (unchanged behavior)
- Heartbeat tasks marked failed
- Sub-agent tasks marked failed
- Sub-agent with resumable parent handled correctly
- Recovery notification created
- Resume sets status to running
- Resume restores conversation
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents import agent_runner
from backend.openloop.agents.agent_runner import (
    _is_resumable,
    recover_from_crash,
    resume_autonomous_tasks,
)
from backend.openloop.db.models import BackgroundTask, Notification
from backend.openloop.services import (
    agent_service,
    background_task_service,
    conversation_service,
    space_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(db: Session, name: str = "TestAgent", **kwargs):
    return agent_service.create_agent(db, name=name, **kwargs)


def _make_space(db: Session, name: str = "Test Space"):
    return space_service.create_space(db, name=name, template="project")


def _make_conversation(db: Session, space_id: str, agent_id: str, **kwargs):
    return conversation_service.create_conversation(
        db,
        space_id=space_id,
        agent_id=agent_id,
        name="Test Conversation",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# recover_from_crash tests
# ---------------------------------------------------------------------------


class TestRecoverFromCrash:
    def test_autonomous_task_with_remaining_items_set_to_pending_resume(
        self, db_session: Session
    ):
        """Autonomous task with mix of completed and pending items should be pending_resume."""
        agent = _make_agent(db_session, name="ResumeAgent1")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Autonomous work",
            run_type="autonomous",
            status="running",
            goal="Build features",
            task_list=[
                {"title": "Step 1", "status": "completed"},
                {"title": "Step 2", "status": "pending"},
                {"title": "Step 3", "status": "pending"},
            ],
        )
        background_task_service.update_background_task(
            db_session,
            task.id,
            completed_count=1,
            total_count=3,
        )

        recover_from_crash(db_session)

        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "pending_resume"

    def test_autonomous_task_without_task_list_marked_failed(
        self, db_session: Session
    ):
        """Autonomous task with no task_list should be marked failed."""
        agent = _make_agent(db_session, name="NoListAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Autonomous work",
            run_type="autonomous",
            status="running",
            goal="Build features",
        )

        recover_from_crash(db_session)

        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "failed"

    def test_autonomous_task_all_completed_marked_failed(
        self, db_session: Session
    ):
        """Autonomous task with all items completed should be marked failed."""
        agent = _make_agent(db_session, name="AllDoneAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Autonomous work",
            run_type="autonomous",
            status="running",
            goal="Build features",
            task_list=[
                {"title": "Step 1", "status": "completed"},
                {"title": "Step 2", "status": "completed"},
            ],
        )
        background_task_service.update_background_task(
            db_session,
            task.id,
            completed_count=2,
            total_count=2,
        )

        recover_from_crash(db_session)

        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "failed"

    def test_autonomous_task_without_goal_marked_failed(
        self, db_session: Session
    ):
        """Autonomous task with pending items but no goal should be marked failed."""
        agent = _make_agent(db_session, name="NoGoalAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Autonomous work",
            run_type="autonomous",
            status="running",
            task_list=[
                {"title": "Step 1", "status": "pending"},
            ],
        )

        recover_from_crash(db_session)

        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "failed"

    def test_regular_task_still_marked_failed(self, db_session: Session):
        """Regular task should still be marked failed (unchanged behavior)."""
        agent = _make_agent(db_session, name="RegularAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Regular work",
            run_type="task",
            status="running",
        )

        recover_from_crash(db_session)

        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "failed"
        assert updated.error == "Server restarted during execution"

    def test_heartbeat_task_marked_failed(self, db_session: Session):
        """Heartbeat task should be marked failed."""
        agent = _make_agent(db_session, name="HeartbeatAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Heartbeat check",
            run_type="heartbeat",
            status="running",
        )

        recover_from_crash(db_session)

        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "failed"
        assert updated.error == "Server restarted during execution"

    def test_subagent_with_failed_parent_marked_failed(self, db_session: Session):
        """Sub-agent task and its non-resumable parent should both be marked failed."""
        agent = _make_agent(db_session, name="ParentAgent")
        parent_task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Autonomous parent",
            run_type="autonomous",
            status="running",
            goal="Parent goal",
            # No task_list -> not resumable
        )
        child_task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Sub-agent work",
            run_type="task",
            status="running",
            parent_task_id=parent_task.id,
        )

        recover_from_crash(db_session)

        db_session.expire_all()
        updated_parent = background_task_service.get_background_task(
            db_session, parent_task.id
        )
        updated_child = background_task_service.get_background_task(
            db_session, child_task.id
        )
        assert updated_parent.status == "failed"
        assert updated_child.status == "failed"
        assert "sub-agent" in updated_child.error

    def test_subagent_with_resumable_parent(self, db_session: Session):
        """Sub-agent task should be failed; resumable parent should be pending_resume."""
        agent = _make_agent(db_session, name="ResumableParentAgent")
        parent_task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Autonomous parent",
            run_type="autonomous",
            status="running",
            goal="Parent goal",
            task_list=[
                {"title": "Step 1", "status": "completed"},
                {"title": "Step 2", "status": "pending"},
            ],
        )
        background_task_service.update_background_task(
            db_session,
            parent_task.id,
            completed_count=1,
            total_count=2,
        )
        child_task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Sub-agent work",
            run_type="task",
            status="running",
            parent_task_id=parent_task.id,
        )

        recover_from_crash(db_session)

        db_session.expire_all()
        updated_parent = background_task_service.get_background_task(
            db_session, parent_task.id
        )
        updated_child = background_task_service.get_background_task(
            db_session, child_task.id
        )
        assert updated_parent.status == "pending_resume"
        assert updated_child.status == "failed"
        assert "sub-agent" in updated_child.error

    def test_recovery_notification_created(self, db_session: Session):
        """After recovery with autonomous tasks, a notification should be created."""
        agent = _make_agent(db_session, name="NotifAgent")
        # Create a resumable autonomous task
        background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Autonomous work",
            run_type="autonomous",
            status="running",
            goal="Build features",
            task_list=[
                {"title": "Step 1", "status": "pending"},
            ],
        )
        # Create a regular task that will fail
        background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Regular work",
            run_type="task",
            status="running",
        )

        recover_from_crash(db_session)

        # Check notification was created
        notifications = (
            db_session.query(Notification)
            .filter(Notification.title == "System recovered")
            .all()
        )
        assert len(notifications) == 1
        notif = notifications[0]
        assert "1 autonomous run(s) queued for resume" in notif.body
        assert "1 task(s) marked failed" in notif.body


# ---------------------------------------------------------------------------
# _is_resumable tests
# ---------------------------------------------------------------------------


class TestIsResumable:
    def test_resumable_with_pending_items(self):
        task = BackgroundTask(
            goal="Some goal",
            task_list=[
                {"title": "A", "status": "completed"},
                {"title": "B", "status": "pending"},
            ],
        )
        assert _is_resumable(task) is True

    def test_not_resumable_without_goal(self):
        task = BackgroundTask(
            goal=None,
            task_list=[{"title": "A", "status": "pending"}],
        )
        assert _is_resumable(task) is False

    def test_not_resumable_without_task_list(self):
        task = BackgroundTask(
            goal="Some goal",
            task_list=None,
        )
        assert _is_resumable(task) is False

    def test_not_resumable_all_completed(self):
        task = BackgroundTask(
            goal="Some goal",
            task_list=[
                {"title": "A", "status": "completed"},
                {"title": "B", "status": "completed"},
            ],
        )
        assert _is_resumable(task) is False


# ---------------------------------------------------------------------------
# resume_autonomous_tasks tests
# ---------------------------------------------------------------------------


class TestResumeAutonomousTasks:
    @pytest.mark.asyncio
    async def test_resume_sets_status_to_running(self, db_session: Session):
        """Task with status pending_resume should be set to running after resume."""
        agent = _make_agent(db_session, name="ResumeRunAgent")
        space = _make_space(db_session, name="Resume Space")
        conv = _make_conversation(db_session, space_id=space.id, agent_id=agent.id)

        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Resumable work",
            run_type="autonomous",
            status="pending_resume",
            goal="Resume goal",
            space_id=space.id,
            conversation_id=conv.id,
            task_list=[{"title": "Step 1", "status": "pending"}],
        )

        with patch(
            "backend.openloop.agents.agent_runner._run_autonomous_task",
            new_callable=AsyncMock,
        ):
            count = await resume_autonomous_tasks(db_session)

        assert count == 1
        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "running"

    @pytest.mark.asyncio
    async def test_resume_restores_conversation(self, db_session: Session):
        """Conversation linked to pending_resume task should be restored to active."""
        agent = _make_agent(db_session, name="ResumeConvAgent")
        space = _make_space(db_session, name="Conv Space")
        conv = _make_conversation(db_session, space_id=space.id, agent_id=agent.id)
        # Mark conversation as interrupted (as crash recovery would)
        conversation_service.update_conversation(
            db_session, conv.id, status="interrupted"
        )

        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Resumable work",
            run_type="autonomous",
            status="pending_resume",
            goal="Resume goal",
            space_id=space.id,
            conversation_id=conv.id,
            task_list=[{"title": "Step 1", "status": "pending"}],
        )

        with patch(
            "backend.openloop.agents.agent_runner._run_autonomous_task",
            new_callable=AsyncMock,
        ):
            count = await resume_autonomous_tasks(db_session)

        assert count == 1
        db_session.expire_all()
        updated_conv = conversation_service.get_conversation(db_session, conv.id)
        assert updated_conv.status == "active"

    @pytest.mark.asyncio
    async def test_resume_no_pending_returns_zero(self, db_session: Session):
        """When no tasks are pending_resume, should return 0."""
        count = await resume_autonomous_tasks(db_session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_resume_creates_notification(self, db_session: Session):
        """Resume should create a notification for each resumed task."""
        agent = _make_agent(db_session, name="NotifResumeAgent")
        space = _make_space(db_session, name="Notif Space")
        conv = _make_conversation(db_session, space_id=space.id, agent_id=agent.id)

        background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Resumable work",
            run_type="autonomous",
            status="pending_resume",
            goal="Resume notification goal",
            space_id=space.id,
            conversation_id=conv.id,
            task_list=[{"title": "Step 1", "status": "pending"}],
        )

        with patch(
            "backend.openloop.agents.agent_runner._run_autonomous_task",
            new_callable=AsyncMock,
        ):
            await resume_autonomous_tasks(db_session)

        notifications = (
            db_session.query(Notification)
            .filter(Notification.title == "Autonomous run resumed")
            .all()
        )
        assert len(notifications) == 1
        assert "Resume notification goal" in notifications[0].body
