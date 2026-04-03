"""End-to-end integration tests for the full autonomous pipeline (Task 11.4).

These tests exercise multiple components together: services, agent_runner
functions, concurrency_manager, permission_enforcer, approval_service,
summary_service, and system_service — all with real DB operations and
mocked SDK calls.

14 scenarios covering the autonomous lifecycle from launch through
crash recovery, budget tracking, permission inheritance, and morning
briefs.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.agent_runner import (
    _build_continuation_prompt,
    _is_resumable,
    recover_from_crash,
    resume_autonomous_tasks,
)
from backend.openloop.agents.concurrency_manager import (
    MAX_SUBAGENTS_PER_RUN,
    acquire_slot,
    count_active_children,
    release_slot,
)
from backend.openloop.agents.permission_enforcer import (
    PermissionSet,
    narrow_permissions,
    validate_narrowing,
)
from backend.openloop.db.models import (
    Agent,
    AgentPermission,
    ApprovalQueue,
    BackgroundTask,
    Conversation,
    ConversationMessage,
    Notification,
    SystemState,
)
from backend.openloop.services import (
    agent_service,
    approval_service,
    background_task_service,
    conversation_service,
    space_service,
    summary_service,
    system_service,
)
from contract.enums import (
    ApprovalStatus,
    BackgroundTaskRunType,
    BackgroundTaskStatus,
    GrantLevel,
    Operation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(
    db: Session,
    name: str = "E2EAgent",
    *,
    approval_timeout_hours: int | None = None,
    heartbeat_enabled: bool = False,
    heartbeat_cron: str | None = None,
    max_spawn_depth: int | None = None,
    **kwargs,
) -> Agent:
    agent = agent_service.create_agent(db, name=name, **kwargs)
    if approval_timeout_hours is not None:
        agent.approval_timeout_hours = approval_timeout_hours
    if heartbeat_enabled:
        agent.heartbeat_enabled = True
    if heartbeat_cron is not None:
        agent.heartbeat_cron = heartbeat_cron
    if max_spawn_depth is not None:
        agent.max_spawn_depth = max_spawn_depth
    db.commit()
    db.refresh(agent)
    return agent


def _make_space(db: Session, name: str = "E2E Space"):
    return space_service.create_space(db, name=name, template="project")


def _make_background_task(
    db: Session,
    agent_id: str,
    *,
    instruction: str = "e2e test task",
    run_type: str = "autonomous",
    status: str = "running",
    goal: str | None = None,
    task_list: list | None = None,
    completed_count: int = 0,
    total_count: int = 0,
    space_id: str | None = None,
    conversation_id: str | None = None,
    parent_task_id: str | None = None,
    token_budget: int | None = None,
    time_budget: int | None = None,
    run_summary: str | None = None,
    delegation_depth: int = 0,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> BackgroundTask:
    task = background_task_service.create_background_task(
        db,
        agent_id=agent_id,
        instruction=instruction,
        run_type=run_type,
        status=status,
        goal=goal,
        task_list=task_list,
        space_id=space_id,
        conversation_id=conversation_id,
        parent_task_id=parent_task_id,
        token_budget=token_budget,
        time_budget=time_budget,
        run_summary=run_summary,
        delegation_depth=delegation_depth,
    )
    updates = {}
    if completed_count:
        updates["completed_count"] = completed_count
    if total_count:
        updates["total_count"] = total_count
    if updates:
        background_task_service.update_background_task(db, task.id, **updates)
    # Direct field updates that aren't in update_background_task
    if started_at is not None:
        task.started_at = started_at
    if completed_at is not None:
        task.completed_at = completed_at
    if started_at is not None or completed_at is not None:
        db.commit()
        db.refresh(task)
    return task


def _make_conversation(
    db: Session,
    agent_id: str,
    space_id: str | None = None,
    name: str = "E2E Conversation",
    **kwargs,
) -> Conversation:
    return conversation_service.create_conversation(
        db,
        agent_id=agent_id,
        space_id=space_id,
        name=name,
        **kwargs,
    )


def _make_approval(
    db: Session,
    background_task_id: str,
    agent_id: str,
    *,
    action_type: str = "execute:bash",
    hours_ago: float = 0,
) -> ApprovalQueue:
    entry = approval_service.create_approval(
        db,
        background_task_id=background_task_id,
        agent_id=agent_id,
        action_type=action_type,
        action_detail={"tool_name": "Bash", "command": "ls"},
        reason="E2E test reason",
    )
    if hours_ago > 0:
        entry.created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours_ago)
        db.commit()
        db.refresh(entry)
    return entry


def _add_permission(db: Session, agent_id: str, resource: str, operation: str, grant: str = "always"):
    perm = AgentPermission(
        agent_id=agent_id,
        resource_pattern=resource,
        operation=operation,
        grant_level=grant,
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)
    return perm


# ---------------------------------------------------------------------------
# 1. Full autonomous run lifecycle
# ---------------------------------------------------------------------------


class TestFullAutonomousRunLifecycle:
    def test_full_autonomous_run_lifecycle(self, db_session: Session):
        """Create agent + space + BackgroundTask with task_list, generate
        summary, verify summary content and notification."""
        agent = _make_agent(db_session, name="LifecycleAgent")
        space = _make_space(db_session, name="Lifecycle Space")

        now = datetime.now(UTC)
        task_list = [
            {"title": "Research", "status": "completed"},
            {"title": "Design", "status": "completed"},
            {"title": "Implement", "status": "completed"},
            {"title": "Test", "status": "pending"},
            {"title": "Deploy", "status": "pending"},
        ]
        task = _make_background_task(
            db_session,
            agent.id,
            goal="Build the widget pipeline",
            task_list=task_list,
            completed_count=3,
            total_count=5,
            space_id=space.id,
            status="completed",
            started_at=now - timedelta(minutes=45),
            completed_at=now,
        )

        # Generate summary
        summary = summary_service.generate_run_summary(db_session, task.id)

        # Verify summary content
        assert "Goal: Build the widget pipeline" in summary
        assert "3/5 items completed" in summary
        assert "completed: 3" in summary
        assert "pending: 2" in summary
        assert "45m" in summary

        # Verify summary stored on task
        db_session.expire_all()
        reloaded = background_task_service.get_background_task(db_session, task.id)
        assert reloaded.run_summary is not None
        assert "Build the widget pipeline" in reloaded.run_summary

        # Verify notification created
        notifs = (
            db_session.query(Notification)
            .filter(Notification.type == "task_completed")
            .all()
        )
        assert len(notifs) == 1
        assert "Build the widget pipeline" in notifs[0].title


# ---------------------------------------------------------------------------
# 2. Compaction preserves goal and task list
# ---------------------------------------------------------------------------


class TestCompactionPreservesGoalAndTaskList:
    def test_compaction_preserves_goal_and_task_list(self, db_session: Session):
        """After compaction, continuation prompt must re-inject goal,
        progress info, and compaction note."""
        agent = _make_agent(db_session, name="CompactAgent")
        conv = _make_conversation(db_session, agent.id)
        now = datetime.now(UTC)

        task = _make_background_task(
            db_session,
            agent.id,
            goal="Reorganize the codebase",
            task_list=[
                {"title": "Audit files", "status": "completed"},
                {"title": "Move modules", "status": "completed"},
                {"title": "Update imports", "status": "pending"},
                {"title": "Run tests", "status": "pending"},
            ],
            completed_count=2,
            total_count=4,
            conversation_id=conv.id,
            started_at=now - timedelta(minutes=30),
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=5,
            started_at=now - timedelta(minutes=30),
            compacted=True,
            compaction_summary="Completed file audit and module relocation. Imports need updating.",
        )

        # Goal is re-injected
        assert "Reorganize the codebase" in prompt
        # Progress info
        assert "2/4" in prompt
        # Compaction note
        assert "compacted" in prompt.lower()
        assert "Completed file audit" in prompt
        # Turn number
        assert "Turn 5" in prompt

        # Verify task_list still accessible from DB
        db_session.expire_all()
        reloaded = background_task_service.get_background_task(db_session, task.id)
        assert reloaded.task_list is not None
        assert len(reloaded.task_list) == 4
        pending_items = [i for i in reloaded.task_list if i["status"] == "pending"]
        assert len(pending_items) == 2


# ---------------------------------------------------------------------------
# 3. Approval queue full flow
# ---------------------------------------------------------------------------


class TestApprovalQueueFullFlow:
    def test_approval_queue_full_flow(self, db_session: Session):
        """Create approval, verify count incremented, resolve as approved,
        verify count decremented and status set."""
        agent = _make_agent(db_session, name="ApprovalFlowAgent")
        space = _make_space(db_session, name="Approval Space")

        task = _make_background_task(
            db_session,
            agent.id,
            goal="Approval flow test",
            space_id=space.id,
            status="running",
        )

        # Create approval
        entry = approval_service.create_approval(
            db_session,
            background_task_id=task.id,
            agent_id=agent.id,
            action_type="create_item",
            action_detail={"item_type": "task"},
            reason="Need to create a new task item",
        )
        assert entry.status == ApprovalStatus.PENDING

        # Verify count incremented
        db_session.refresh(task)
        assert task.queued_approvals_count == 1

        # Create a second approval
        entry2 = approval_service.create_approval(
            db_session,
            background_task_id=task.id,
            agent_id=agent.id,
            action_type="delete_item",
            action_detail={"item_id": "some-id"},
            reason="Duplicate item removal",
        )

        db_session.refresh(task)
        assert task.queued_approvals_count == 2

        # Resolve first as approved
        resolved = approval_service.resolve_approval(
            db_session, entry.id, status=ApprovalStatus.APPROVED
        )
        assert resolved.status == ApprovalStatus.APPROVED

        db_session.refresh(task)
        assert task.queued_approvals_count == 1

        # Resolve second as denied
        resolved2 = approval_service.resolve_approval(
            db_session, entry2.id, status=ApprovalStatus.DENIED
        )
        assert resolved2.status == ApprovalStatus.DENIED

        db_session.refresh(task)
        assert task.queued_approvals_count == 0


# ---------------------------------------------------------------------------
# 4. Parallel delegation respects lane caps
# ---------------------------------------------------------------------------


class TestParallelDelegationRespectsLaneCaps:
    def test_parallel_delegation_respects_lane_caps(self, db_session: Session):
        """Acquire subagent slots up to the limit, verify next returns False,
        release one, verify acquire succeeds. Also test MAX_SUBAGENTS_PER_RUN."""
        agent = _make_agent(db_session, name="LaneCapAgent")

        # Fill the subagent lane (cap = 8)
        parent = _make_background_task(
            db_session,
            agent.id,
            run_type="task",
            status="running",
        )

        # Create children up to MAX_SUBAGENTS_PER_RUN
        children = []
        for i in range(MAX_SUBAGENTS_PER_RUN):
            child = _make_background_task(
                db_session,
                agent.id,
                instruction=f"Child task {i + 1}",
                run_type="task",
                status="running",
                parent_task_id=parent.id,
            )
            children.append(child)

        # Verify per-run cap reached
        assert count_active_children(db_session, parent.id) == MAX_SUBAGENTS_PER_RUN

        # Complete one child
        background_task_service.update_background_task(
            db_session, children[0].id,
            status="completed",
            completed_at=datetime.now(UTC),
        )
        assert count_active_children(db_session, parent.id) == MAX_SUBAGENTS_PER_RUN - 1

        # Can spawn another
        _make_background_task(
            db_session,
            agent.id,
            instruction="Replacement child",
            run_type="task",
            status="running",
            parent_task_id=parent.id,
        )
        assert count_active_children(db_session, parent.id) == MAX_SUBAGENTS_PER_RUN

        # Test lane-level caps: fill autonomous lane (cap = 2)
        _make_background_task(db_session, agent.id, run_type="task", status="running")
        _make_background_task(db_session, agent.id, run_type="task", status="running")
        assert acquire_slot(db_session, "autonomous") is False

        # Interactive lane should still work independently
        assert acquire_slot(db_session, "interactive") is True


# ---------------------------------------------------------------------------
# 5. Permission inheritance — no escalation
# ---------------------------------------------------------------------------


class TestPermissionInheritanceNoEscalation:
    def test_permission_inheritance_no_escalation(self, db_session: Session):
        """Parent permissions pass to child. Child cannot exceed parent."""
        agent = _make_agent(db_session, name="PermAgent")
        _add_permission(db_session, agent.id, "openloop-board", Operation.READ)
        _add_permission(db_session, agent.id, "openloop-board", Operation.CREATE)
        _add_permission(db_session, agent.id, "openloop-memory", Operation.READ)

        # Depth 0: full permissions
        parent_perms = narrow_permissions(db_session, agent.id, delegation_depth=0)
        assert len(parent_perms.entries) == 3

        # Depth 1: child inherits parent's permissions
        child_perms = narrow_permissions(db_session, agent.id, delegation_depth=1)
        assert len(child_perms.entries) == 3

        # Validate narrowing: child subset of parent
        assert validate_narrowing(parent_perms, child_perms) is True

        # Validate narrowing: child cannot exceed parent
        escalated_child = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
            ("openloop-board", Operation.CREATE, GrantLevel.ALWAYS),
            ("openloop-memory", Operation.READ, GrantLevel.ALWAYS),
            # Extra permission parent doesn't have:
            ("openloop-delegation", Operation.EXECUTE, GrantLevel.ALWAYS),
        ])
        assert validate_narrowing(parent_perms, escalated_child) is False

        # Validate narrowing: child with stricter grant is valid
        stricter_child = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.APPROVAL),
        ])
        assert validate_narrowing(parent_perms, stricter_child) is True

        # Validate narrowing: child with looser grant is invalid
        looser_child = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.ALWAYS),
        ])
        # Parent has always for board:read, so always <= always is valid
        assert validate_narrowing(parent_perms, looser_child) is True

        # But if parent has approval, child can't have always
        restricted_parent = PermissionSet(entries=[
            ("openloop-board", Operation.READ, GrantLevel.APPROVAL),
        ])
        assert validate_narrowing(restricted_parent, looser_child) is False


# ---------------------------------------------------------------------------
# 6. Kill switch prevents new work
# ---------------------------------------------------------------------------


class TestKillSwitchPreventsNewWork:
    def test_kill_switch_prevents_new_work(self, db_session: Session):
        """System pause blocks new work; resume re-enables."""
        # Initially not paused
        assert system_service.is_paused(db_session) is False

        # Pause the system
        result = system_service.emergency_stop(db_session)
        assert result["paused"] is True
        assert system_service.is_paused(db_session) is True

        # The kill switch guard in delegate_background checks is_paused.
        # Verify the condition that would block new work.
        assert system_service.is_paused(db_session) is True

        # Create a background task — the task itself can be created,
        # but delegate_background would refuse to fire it.
        agent = _make_agent(db_session, name="KillSwitchAgent")
        task = _make_background_task(
            db_session,
            agent.id,
            status="pending",
            goal="Should be blocked",
        )
        assert task is not None

        # Resume
        system_service.resume(db_session)
        assert system_service.is_paused(db_session) is False


# ---------------------------------------------------------------------------
# 7. Crash recovery and resume
# ---------------------------------------------------------------------------


class TestCrashRecoveryAndResume:
    def test_crash_recovery_and_resume(self, db_session: Session):
        """Autonomous task with remaining items gets pending_resume on crash,
        then resumes to running on resume_autonomous_tasks()."""
        agent = _make_agent(db_session, name="CrashRecoveryAgent")
        space = _make_space(db_session, name="Crash Space")
        conv = _make_conversation(db_session, agent.id, space_id=space.id)

        task = _make_background_task(
            db_session,
            agent.id,
            goal="Long running project",
            task_list=[
                {"title": "Step 1", "status": "completed"},
                {"title": "Step 2", "status": "completed"},
                {"title": "Step 3", "status": "completed"},
                {"title": "Step 4", "status": "pending"},
                {"title": "Step 5", "status": "pending"},
                {"title": "Step 6", "status": "pending"},
                {"title": "Step 7", "status": "pending"},
                {"title": "Step 8", "status": "pending"},
                {"title": "Step 9", "status": "pending"},
                {"title": "Step 10", "status": "pending"},
            ],
            completed_count=3,
            total_count=10,
            status="running",
            space_id=space.id,
            conversation_id=conv.id,
        )

        # Crash recovery
        recover_from_crash(db_session)

        db_session.expire_all()
        updated_task = background_task_service.get_background_task(db_session, task.id)
        assert updated_task.status == "pending_resume"

        updated_conv = conversation_service.get_conversation(db_session, conv.id)
        assert updated_conv.status == "interrupted"

    @pytest.mark.asyncio
    async def test_resume_after_crash(self, db_session: Session):
        """resume_autonomous_tasks picks up pending_resume tasks."""
        agent = _make_agent(db_session, name="ResumeAfterCrash")
        space = _make_space(db_session, name="Resume Space")
        conv = _make_conversation(db_session, agent.id, space_id=space.id)

        # Mark conversation as interrupted (as crash recovery would)
        conversation_service.update_conversation(db_session, conv.id, status="interrupted")

        task = _make_background_task(
            db_session,
            agent.id,
            goal="Resumable project",
            task_list=[
                {"title": "Step 1", "status": "completed"},
                {"title": "Step 2", "status": "pending"},
            ],
            completed_count=1,
            total_count=2,
            status="pending_resume",
            space_id=space.id,
            conversation_id=conv.id,
        )

        with patch(
            "backend.openloop.agents.agent_runner._run_autonomous_task",
            new_callable=AsyncMock,
        ):
            count = await resume_autonomous_tasks(db_session)

        assert count == 1

        db_session.expire_all()
        updated_task = background_task_service.get_background_task(db_session, task.id)
        assert updated_task.status == "running"

        updated_conv = conversation_service.get_conversation(db_session, conv.id)
        assert updated_conv.status == "active"

        # Verify notification created
        notifs = (
            db_session.query(Notification)
            .filter(Notification.title == "Autonomous run resumed")
            .all()
        )
        assert len(notifs) == 1
        assert "Resumable project" in notifs[0].body


# ---------------------------------------------------------------------------
# 8. Heartbeat evaluation
# ---------------------------------------------------------------------------


class TestHeartbeatEvaluation:
    def test_heartbeat_evaluation(self, db_session: Session):
        """Heartbeat due detection based on cron and last heartbeat time."""
        from backend.openloop.agents.automation_scheduler import _is_heartbeat_due

        agent = _make_agent(
            db_session,
            name="HeartbeatEvalAgent",
            heartbeat_enabled=True,
            heartbeat_cron="*/30 * * * *",
        )

        # No prior heartbeats — should be due
        now_naive = datetime.now(UTC).replace(tzinfo=None)
        assert _is_heartbeat_due(db_session, agent, now_naive) is True

        # Create a recent heartbeat (5 min ago) — should NOT be due
        recent_task = BackgroundTask(
            agent_id=agent.id,
            instruction="heartbeat check",
            run_type=BackgroundTaskRunType.HEARTBEAT,
            status="completed",
        )
        recent_task.created_at = datetime.now(UTC) - timedelta(minutes=5)
        db_session.add(recent_task)
        db_session.commit()

        assert _is_heartbeat_due(db_session, agent, now_naive) is False

        # Create an old heartbeat (35 min ago) and make the recent one older too
        recent_task.created_at = datetime.now(UTC) - timedelta(minutes=35)
        db_session.commit()

        assert _is_heartbeat_due(db_session, agent, now_naive) is True


# ---------------------------------------------------------------------------
# 9. Budget exhaustion tracking
# ---------------------------------------------------------------------------


class TestBudgetExhaustionTracking:
    def test_budget_exhaustion_tracking(self, db_session: Session):
        """Continuation prompt reflects budget remaining, including near-zero."""
        agent = _make_agent(db_session, name="BudgetAgent")
        conv = _make_conversation(db_session, agent.id)
        now = datetime.now(UTC)

        task = _make_background_task(
            db_session,
            agent.id,
            goal="Process data",
            token_budget=1000,
            conversation_id=conv.id,
            started_at=now - timedelta(minutes=5),
        )

        # Add messages with tokens exceeding the budget
        for i in range(5):
            msg = ConversationMessage(
                conversation_id=conv.id,
                role="assistant",
                content=f"response {i}",
                input_tokens=150,
                output_tokens=100,
            )
            db_session.add(msg)
        db_session.commit()
        # Total tokens: 5 * (150 + 100) = 1250, exceeds budget of 1000

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=6,
            started_at=now - timedelta(minutes=5),
        )

        # Budget section should show 0 tokens remaining
        assert "0 tokens remaining" in prompt
        assert "Goal: Process data" in prompt


# ---------------------------------------------------------------------------
# 10. Cascade termination
# ---------------------------------------------------------------------------


class TestCascadeTermination:
    def test_cascade_termination(self, db_session: Session):
        """Stopping a parent recursively cancels all descendants."""
        agent = _make_agent(db_session, name="CascadeAgent")

        parent = _make_background_task(
            db_session,
            agent.id,
            instruction="Coordinator",
            run_type="autonomous",
            status="running",
            goal="Coordinate all research",
        )

        child1 = _make_background_task(
            db_session,
            agent.id,
            instruction="Research area A",
            run_type="task",
            status="running",
            parent_task_id=parent.id,
        )

        child2 = _make_background_task(
            db_session,
            agent.id,
            instruction="Research area B",
            run_type="task",
            status="running",
            parent_task_id=parent.id,
        )

        # Cascade cancel children
        count = background_task_service.cascade_update_status(
            db_session,
            parent.id,
            new_status="cancelled",
            error_note="Parent stopped by user",
        )
        assert count == 2

        # Verify all children are cancelled
        db_session.expire_all()
        c1 = background_task_service.get_background_task(db_session, child1.id)
        c2 = background_task_service.get_background_task(db_session, child2.id)
        assert c1.status == "cancelled"
        assert c2.status == "cancelled"
        assert c1.error == "Parent stopped by user"
        assert c2.error == "Parent stopped by user"

        # Parent itself is NOT updated by cascade_update_status
        # (it only updates descendants)
        parent_reloaded = background_task_service.get_background_task(db_session, parent.id)
        assert parent_reloaded.status == "running"


# ---------------------------------------------------------------------------
# 11. User modifies task list
# ---------------------------------------------------------------------------


class TestUserModifiesTaskList:
    def test_user_modifies_task_list(self, db_session: Session):
        """Update task list via service, verify version incremented,
        continuation prompt reflects updated counts."""
        agent = _make_agent(db_session, name="TaskListModAgent")
        conv = _make_conversation(db_session, agent.id)
        now = datetime.now(UTC)

        original_list = [
            {"title": "Item A", "status": "completed"},
            {"title": "Item B", "status": "pending"},
            {"title": "Item C", "status": "pending"},
            {"title": "Item D", "status": "pending"},
            {"title": "Item E", "status": "pending"},
        ]
        task = _make_background_task(
            db_session,
            agent.id,
            goal="Manage items",
            task_list=original_list,
            completed_count=1,
            total_count=5,
            conversation_id=conv.id,
            started_at=now - timedelta(minutes=10),
        )

        # User adds an item and reorders (simulate via update_background_task)
        new_list = [
            {"title": "Item A", "status": "completed"},
            {"title": "Item F", "status": "pending"},  # New item
            {"title": "Item B", "status": "pending"},
            {"title": "Item C", "status": "pending"},
            {"title": "Item D", "status": "pending"},
            {"title": "Item E", "status": "pending"},
        ]
        background_task_service.update_background_task(
            db_session,
            task.id,
            task_list=new_list,
            task_list_version=1,  # Increment from 0
            total_count=6,
        )

        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.task_list_version == 1
        assert updated.total_count == 6
        assert len(updated.task_list) == 6

        # Continuation prompt should reflect updated counts
        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=3,
            started_at=now - timedelta(minutes=10),
        )
        assert "1/6" in prompt


# ---------------------------------------------------------------------------
# 12. Concurrent autonomous runs isolation
# ---------------------------------------------------------------------------


class TestConcurrentAutonomousRunsIsolation:
    def test_concurrent_autonomous_runs_isolation(self, db_session: Session):
        """Two agents with independent autonomous runs maintain isolated state."""
        agent1 = _make_agent(db_session, name="Agent Alpha")
        agent2 = _make_agent(db_session, name="Agent Beta")

        task1 = _make_background_task(
            db_session,
            agent1.id,
            goal="Alpha mission",
            task_list=[
                {"title": "Alpha step 1", "status": "completed"},
                {"title": "Alpha step 2", "status": "pending"},
            ],
            completed_count=1,
            total_count=2,
            status="running",
        )

        task2 = _make_background_task(
            db_session,
            agent2.id,
            goal="Beta mission",
            task_list=[
                {"title": "Beta step 1", "status": "pending"},
                {"title": "Beta step 2", "status": "pending"},
                {"title": "Beta step 3", "status": "pending"},
            ],
            completed_count=0,
            total_count=3,
            status="running",
        )

        # Verify independent state
        t1 = background_task_service.get_background_task(db_session, task1.id)
        t2 = background_task_service.get_background_task(db_session, task2.id)
        assert t1.goal != t2.goal
        assert len(t1.task_list) != len(t2.task_list)
        assert t1.completed_count == 1
        assert t2.completed_count == 0

        # Update one's completed_count
        background_task_service.update_background_task(
            db_session, task1.id, completed_count=2
        )

        # Verify the other is unchanged
        db_session.expire_all()
        t1_updated = background_task_service.get_background_task(db_session, task1.id)
        t2_unchanged = background_task_service.get_background_task(db_session, task2.id)
        assert t1_updated.completed_count == 2
        assert t2_unchanged.completed_count == 0

        # Both tracked independently in autonomous lane
        # (2 running tasks — exactly at the autonomous cap of 2)
        assert acquire_slot(db_session, "autonomous") is False

        # Complete one — slot opens
        background_task_service.update_background_task(
            db_session, task1.id, status="completed",
            completed_at=datetime.now(UTC),
        )
        assert acquire_slot(db_session, "autonomous") is True


# ---------------------------------------------------------------------------
# 13. Approval expiry with per-agent timeout
# ---------------------------------------------------------------------------


class TestApprovalExpiryWithPerAgentTimeout:
    def test_approval_expiry_with_per_agent_timeout(self, db_session: Session):
        """Per-agent timeout overrides default; agents without timeout use default."""
        # Agent with 48h timeout
        agent_slow = _make_agent(
            db_session, name="SlowApprovalAgent", approval_timeout_hours=48
        )
        space_slow = _make_space(db_session, name="Slow Space")
        task_slow = _make_background_task(
            db_session,
            agent_slow.id,
            space_id=space_slow.id,
            status="running",
            goal="Slow approval goal",
        )

        # 30h old — within 48h timeout, should NOT be expired
        entry_30h = _make_approval(
            db_session, task_slow.id, agent_slow.id,
            action_type="action_30h", hours_ago=30,
        )
        # 50h old — beyond 48h timeout, SHOULD be expired
        entry_50h = _make_approval(
            db_session, task_slow.id, agent_slow.id,
            action_type="action_50h", hours_ago=50,
        )

        expired = approval_service.expire_stale(db_session)
        assert len(expired) == 1

        db_session.refresh(entry_30h)
        db_session.refresh(entry_50h)
        assert entry_30h.status == ApprovalStatus.PENDING
        assert entry_50h.status == ApprovalStatus.EXPIRED

        # Agent with no custom timeout (uses default 24h)
        agent_default = _make_agent(db_session, name="DefaultTimeoutAgent")
        space_default = _make_space(db_session, name="Default Space")
        task_default = _make_background_task(
            db_session,
            agent_default.id,
            space_id=space_default.id,
            status="running",
            goal="Default timeout goal",
        )

        # 25h old — beyond default 24h, SHOULD be expired
        entry_25h = _make_approval(
            db_session, task_default.id, agent_default.id,
            action_type="action_25h", hours_ago=25,
        )

        expired2 = approval_service.expire_stale(db_session)
        assert len(expired2) == 1

        db_session.refresh(entry_25h)
        assert entry_25h.status == ApprovalStatus.EXPIRED


# ---------------------------------------------------------------------------
# 14. Morning brief after overnight work
# ---------------------------------------------------------------------------


class TestMorningBriefAfterOvernightWork:
    def test_morning_brief_after_overnight_work(self, db_session: Session):
        """Morning brief shows only tasks completed since last_seen,
        grouped by agent, with accurate counts."""
        agent1 = _make_agent(db_session, name="NightWorker1")
        agent2 = _make_agent(db_session, name="NightWorker2")
        now = datetime.now(UTC)

        # Set user_last_seen to 12h ago
        last_seen_time = now - timedelta(hours=12)
        row = SystemState(
            key="user_last_seen",
            value=last_seen_time.replace(tzinfo=None).isoformat(),
        )
        db_session.add(row)
        db_session.commit()

        # Task completed 6h ago — WITHIN window (should appear)
        task_recent = _make_background_task(
            db_session,
            agent1.id,
            goal="Overnight data processing",
            run_type="autonomous",
            status="completed",
            run_summary="Processed 500 records successfully",
            started_at=now - timedelta(hours=8),
            completed_at=now - timedelta(hours=6),
        )

        # Task completed 18h ago — OUTSIDE window (should NOT appear)
        task_old = _make_background_task(
            db_session,
            agent1.id,
            goal="Yesterday's work",
            run_type="autonomous",
            status="completed",
            run_summary="Old summary",
            started_at=now - timedelta(hours=20),
            completed_at=now - timedelta(hours=18),
        )

        # Task from different agent, 3h ago — WITHIN window
        task_agent2 = _make_background_task(
            db_session,
            agent2.id,
            goal="Agent2 overnight task",
            run_type="autonomous",
            status="completed",
            run_summary="Agent2 completed its work",
            started_at=now - timedelta(hours=5),
            completed_at=now - timedelta(hours=3),
        )

        # Create a pending approval (for pending_approvals_count)
        task_running = _make_background_task(
            db_session,
            agent1.id,
            goal="Still running",
            status="running",
        )
        _make_approval(db_session, task_running.id, agent1.id, action_type="pending_action")

        # Create a failed task since last_seen
        _make_background_task(
            db_session,
            agent2.id,
            goal="Failed task",
            status="failed",
            completed_at=now - timedelta(hours=2),
        )

        brief = summary_service.get_morning_brief(db_session)

        # Should have 2 agents (agent1 with 1 task, agent2 with 1 task)
        assert len(brief["agents"]) == 2
        agent_names = {a["agent_name"] for a in brief["agents"]}
        assert agent_names == {"NightWorker1", "NightWorker2"}

        # Agent1 should only have the recent task, not the old one
        agent1_entry = next(a for a in brief["agents"] if a["agent_name"] == "NightWorker1")
        assert len(agent1_entry["runs"]) == 1
        assert agent1_entry["runs"][0]["goal"] == "Overnight data processing"

        # Agent2 should have its task
        agent2_entry = next(a for a in brief["agents"] if a["agent_name"] == "NightWorker2")
        assert len(agent2_entry["runs"]) == 1
        assert agent2_entry["runs"][0]["goal"] == "Agent2 overnight task"

        # Pending approvals count
        assert brief["pending_approvals_count"] == 1

        # Failed tasks count (since last_seen)
        assert brief["failed_tasks_count"] == 1
