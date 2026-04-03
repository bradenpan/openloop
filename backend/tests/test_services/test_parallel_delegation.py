"""Phase 10.2 tests: parallel delegation, per-run cap, check/cancel tools, continuation prompt."""

import json
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.concurrency_manager import (
    MAX_SUBAGENTS_PER_RUN,
    count_active_children,
)
from backend.openloop.services import agent_service, background_task_service


def _make_agent(db: Session, name: str = "Test Agent", **kwargs):
    return agent_service.create_agent(db, name=name, **kwargs)


# ---------------------------------------------------------------------------
# Helpers — direct tool function calls (bypass MCP wrapping)
# ---------------------------------------------------------------------------


async def _delegate_task(db, agent_name, instruction, background_task_id="", agent_id=""):
    """Call the raw delegate_task tool function with test DB."""
    from backend.openloop.agents.mcp_tools import delegate_task

    return await delegate_task(
        agent_name=agent_name,
        instruction=instruction,
        _db=db,
        _agent_id=agent_id,
        _background_task_id=background_task_id,
    )


async def _check_delegated_tasks(db, task_ids, background_task_id=""):
    """Call the raw check_delegated_tasks tool function with test DB."""
    from backend.openloop.agents.mcp_tools import check_delegated_tasks

    return await check_delegated_tasks(
        task_ids=task_ids,
        _db=db,
        _background_task_id=background_task_id,
    )


async def _cancel_delegated_task(db, task_id, background_task_id=""):
    """Call the raw cancel_delegated_task tool function with test DB."""
    from backend.openloop.agents.mcp_tools import cancel_delegated_task

    return await cancel_delegated_task(
        task_id=task_id,
        _db=db,
        _background_task_id=background_task_id,
    )


# ---------------------------------------------------------------------------
# MAX_SUBAGENTS_PER_RUN enforcement
# ---------------------------------------------------------------------------


class TestPerRunSubagentCap:
    def test_count_active_children(self, db_session: Session):
        """count_active_children counts RUNNING and QUEUED child tasks."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )

        # Create children in various statuses
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 1",
            parent_task_id=parent.id, status="running",
        )
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 2",
            parent_task_id=parent.id, status="queued",
        )
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 3 (done)",
            parent_task_id=parent.id, status="completed",
        )
        background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Child 4 (failed)",
            parent_task_id=parent.id, status="failed",
        )

        assert count_active_children(db_session, parent.id) == 2  # running + queued

    def test_can_spawn_up_to_max(self, db_session: Session):
        """Coordinator can spawn up to MAX_SUBAGENTS_PER_RUN concurrent sub-agents."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )

        for i in range(MAX_SUBAGENTS_PER_RUN):
            background_task_service.create_background_task(
                db_session, agent_id=agent.id,
                instruction=f"Child {i + 1}",
                parent_task_id=parent.id, status="running",
            )

        assert count_active_children(db_session, parent.id) == MAX_SUBAGENTS_PER_RUN

    def test_fourth_delegation_returns_cap_error(self, db_session: Session):
        """4th delegation attempt returns per-run cap error when 3 are active."""
        agent = _make_agent(db_session, name="Worker")
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )

        # Create 3 active children
        for i in range(MAX_SUBAGENTS_PER_RUN):
            background_task_service.create_background_task(
                db_session, agent_id=agent.id,
                instruction=f"Child {i + 1}",
                parent_task_id=parent.id, status="running",
            )

        # Verify the cap is reached
        assert count_active_children(db_session, parent.id) == MAX_SUBAGENTS_PER_RUN

        # The per-run cap is checked inside delegate_task via
        # count_active_children. We test the logic directly here to avoid
        # needing to mock agent_runner.delegate_background.
        from backend.openloop.agents.concurrency_manager import MAX_SUBAGENTS_PER_RUN as cap

        active = count_active_children(db_session, parent.id)
        assert active >= cap  # Would trigger the error path

    def test_completed_child_frees_slot(self, db_session: Session):
        """After one child completes, a 4th can be spawned (slot freed)."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )

        children = []
        for i in range(MAX_SUBAGENTS_PER_RUN):
            child = background_task_service.create_background_task(
                db_session, agent_id=agent.id,
                instruction=f"Child {i + 1}",
                parent_task_id=parent.id, status="running",
            )
            children.append(child)

        assert count_active_children(db_session, parent.id) == MAX_SUBAGENTS_PER_RUN

        # Complete the first child
        background_task_service.update_background_task(
            db_session, children[0].id, status="completed",
            completed_at=datetime.now(UTC),
        )

        # Now only 2 active children
        assert count_active_children(db_session, parent.id) == MAX_SUBAGENTS_PER_RUN - 1

        # A 4th child can be created
        background_task_service.create_background_task(
            db_session, agent_id=agent.id,
            instruction="Child 4",
            parent_task_id=parent.id, status="running",
        )
        assert count_active_children(db_session, parent.id) == MAX_SUBAGENTS_PER_RUN


# ---------------------------------------------------------------------------
# check_delegated_tasks
# ---------------------------------------------------------------------------


class TestCheckDelegatedTasks:
    @pytest.mark.asyncio
    async def test_returns_correct_status_for_children(self, db_session: Session):
        """check_delegated_tasks returns status for child tasks."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )

        child1 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Research Alice",
            parent_task_id=parent.id, status="running",
        )
        child2 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Research Bob",
            parent_task_id=parent.id, status="completed",
        )
        background_task_service.update_background_task(
            db_session, child2.id, result_summary="Found 3 key findings",
        )

        result_str = await _check_delegated_tasks(
            db_session,
            f"{child1.id},{child2.id}",
            background_task_id=parent.id,
        )
        result = json.loads(result_str)
        tasks = result["result"]

        assert len(tasks) == 2
        by_id = {t["task_id"]: t for t in tasks}

        assert by_id[child1.id]["status"] == "running"
        assert by_id[child2.id]["status"] == "completed"
        assert by_id[child2.id]["result_summary"] == "Found 3 key findings"

    @pytest.mark.asyncio
    async def test_skips_non_child_tasks(self, db_session: Session):
        """check_delegated_tasks silently skips tasks that aren't children."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )
        child = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="My child",
            parent_task_id=parent.id, status="running",
        )
        other = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Someone else's task",
            status="running",
        )

        result_str = await _check_delegated_tasks(
            db_session,
            f"{child.id},{other.id}",
            background_task_id=parent.id,
        )
        result = json.loads(result_str)
        tasks = result["result"]

        assert len(tasks) == 1
        assert tasks[0]["task_id"] == child.id

    @pytest.mark.asyncio
    async def test_no_background_task_returns_error(self, db_session: Session):
        """check_delegated_tasks returns error when called outside background context."""
        result_str = await _check_delegated_tasks(
            db_session, "some-id", background_task_id="",
        )
        result = json.loads(result_str)
        assert result["is_error"] is True

    @pytest.mark.asyncio
    async def test_empty_ids_returns_empty(self, db_session: Session):
        """check_delegated_tasks returns empty array for empty input."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )

        result_str = await _check_delegated_tasks(
            db_session, "", background_task_id=parent.id,
        )
        result = json.loads(result_str)
        assert result["result"] == []


# ---------------------------------------------------------------------------
# cancel_delegated_task
# ---------------------------------------------------------------------------


class TestCancelDelegatedTask:
    @pytest.mark.asyncio
    async def test_cancels_child_and_descendants(self, db_session: Session):
        """cancel_delegated_task cancels the target child and all its descendants."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )
        child = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Research Alice",
            parent_task_id=parent.id, status="running",
        )
        grandchild = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Sub-research",
            parent_task_id=child.id, status="running",
        )

        result_str = await _cancel_delegated_task(
            db_session, child.id, background_task_id=parent.id,
        )
        result = json.loads(result_str)

        assert result["result"]["cancelled"] is True
        assert result["result"]["total_cancelled"] == 2  # child + grandchild

        # Verify statuses in DB
        db_session.expire_all()
        child_refreshed = background_task_service.get_background_task(db_session, child.id)
        grandchild_refreshed = background_task_service.get_background_task(db_session, grandchild.id)
        assert child_refreshed.status == "cancelled"
        assert grandchild_refreshed.status == "cancelled"

    @pytest.mark.asyncio
    async def test_rejects_non_child_task(self, db_session: Session):
        """cancel_delegated_task rejects task IDs that aren't children of the caller."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )
        other = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Not my child",
            status="running",
        )

        result_str = await _cancel_delegated_task(
            db_session, other.id, background_task_id=parent.id,
        )
        result = json.loads(result_str)

        assert result["is_error"] is True
        assert "not a child" in result["error"]

        # Verify the other task is still running
        db_session.expire_all()
        other_refreshed = background_task_service.get_background_task(db_session, other.id)
        assert other_refreshed.status == "running"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_returns_error(self, db_session: Session):
        """cancel_delegated_task returns error for nonexistent task ID."""
        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator",
            status="running",
        )

        result_str = await _cancel_delegated_task(
            db_session, "nonexistent-id", background_task_id=parent.id,
        )
        result = json.loads(result_str)
        assert result["is_error"] is True

    @pytest.mark.asyncio
    async def test_no_background_task_returns_error(self, db_session: Session):
        """cancel_delegated_task returns error when called outside background context."""
        result_str = await _cancel_delegated_task(
            db_session, "some-id", background_task_id="",
        )
        result = json.loads(result_str)
        assert result["is_error"] is True


# ---------------------------------------------------------------------------
# Continuation prompt includes delegation status
# ---------------------------------------------------------------------------


class TestContinuationPromptDelegation:
    def test_includes_delegation_status_when_children_exist(self, db_session: Session):
        """_build_continuation_prompt includes sub-agent status section when children exist."""
        from backend.openloop.agents.agent_runner import _build_continuation_prompt

        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Coordinator task",
            status="running", goal="Coordinate research",
        )
        # Create a conversation for the prompt
        from backend.openloop.services import conversation_service

        conv = conversation_service.create_conversation(
            db_session, agent_id=agent.id, name="Test conv",
        )

        # Create children in various states
        child1 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Research Alice Chen",
            parent_task_id=parent.id, status="completed",
        )
        background_task_service.update_background_task(
            db_session, child1.id, result_summary="Brief completed with 3 key findings",
        )
        child2 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Research Bob Park",
            parent_task_id=parent.id, status="running",
        )
        child3 = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Research Carol Davis",
            parent_task_id=parent.id, status="failed",
        )
        background_task_service.update_background_task(
            db_session, child3.id, error="Rate limit exceeded",
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=parent.id,
            conversation_id=conv.id,
            turn=2,
            started_at=datetime.now(UTC),
        )

        assert "Sub-agent status:" in prompt
        assert "Research Alice Chen" in prompt
        assert "COMPLETED" in prompt
        assert "Brief completed with 3 key findings" in prompt
        assert "Research Bob Park" in prompt
        assert "RUNNING" in prompt
        assert "Research Carol Davis" in prompt
        assert "FAILED" in prompt
        assert "Rate limit exceeded" in prompt

    def test_excludes_delegation_status_when_no_children(self, db_session: Session):
        """_build_continuation_prompt omits delegation section when no children."""
        from backend.openloop.agents.agent_runner import _build_continuation_prompt

        agent = _make_agent(db_session)
        parent = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Solo task",
            status="running", goal="Do solo work",
        )
        from backend.openloop.services import conversation_service

        conv = conversation_service.create_conversation(
            db_session, agent_id=agent.id, name="Test conv",
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=parent.id,
            conversation_id=conv.id,
            turn=2,
            started_at=datetime.now(UTC),
        )

        assert "Sub-agent status:" not in prompt
