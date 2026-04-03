"""Tests for Phase 9.2b: Autonomous launch flow in agent_runner.

Tests cover:
- launch_autonomous creates pending task and conversation
- Duplicate launch for same agent rejected with 409
- approve_autonomous_launch transitions to running
- Task list stored on BackgroundTask after first turn
- update_task_list MCP tool updates task list and counts
- Pause sets status to paused, resume re-enables
- GOAL_COMPLETE stops the run
- PersistentData extractor includes task list
- autonomous_progress SSE event published on progress
"""

from __future__ import annotations

import asyncio
import json
import types
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.agent_runner import (
    PersistentData,
    _extract_task_list_json,
    _paused_tasks,
    _persistent_data_extractors,
    approve_autonomous_launch,
    launch_autonomous,
    pause_autonomous,
    register_persistent_extractor,
    resume_autonomous,
)
from backend.openloop.services import (
    agent_service,
    background_task_service,
    conversation_service,
    space_service,
    system_service,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_space(db: Session, name: str = "Test Space"):
    return space_service.create_space(db, name=name, template="project")


def _make_agent(db: Session, name: str = "TestAgent", **kwargs):
    return agent_service.create_agent(db, name=name, **kwargs)


def _make_conversation(db: Session, space_id: str, agent_id: str, **kwargs):
    return conversation_service.create_conversation(
        db,
        space_id=space_id,
        agent_id=agent_id,
        name="Test Conversation",
        **kwargs,
    )


@pytest.fixture(autouse=True)
def _mock_permission_hooks():
    """Mock _build_hooks_dict so tests don't need the real SDK hook types."""
    with patch(
        "backend.openloop.agents.agent_runner._build_hooks_dict",
        return_value={"PreToolUse": []},
    ):
        yield


@pytest.fixture(autouse=True)
def _clean_paused_tasks():
    """Ensure the paused tasks set is clean for each test."""
    _paused_tasks.clear()
    yield
    _paused_tasks.clear()


@pytest.fixture(autouse=True)
def _mock_system_not_paused():
    """Default: system is not paused."""
    with patch.object(system_service, "is_paused", return_value=False):
        yield


@pytest.fixture(autouse=True)
def _mock_concurrency():
    """Default: concurrency always available."""
    with patch(
        "backend.openloop.agents.agent_runner._check_concurrency",
    ):
        yield


class _NoCloseSession:
    """Wrapper around a SQLAlchemy Session that intercepts close()."""

    def __init__(self, session: Session):
        self._session = session

    def close(self):
        pass

    def rollback(self):
        self._session.rollback()

    def __getattr__(self, name):
        return getattr(self._session, name)


# ---------------------------------------------------------------------------
# Fake SDK types for mocking
# ---------------------------------------------------------------------------


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeResultMessage:
    """Mimics claude_agent_sdk.ResultMessage."""

    def __init__(
        self,
        session_id="fake-session-123",
        result="Hello!",
        is_error=False,
        usage=None,
    ):
        self.session_id = session_id
        self.result = result
        self.is_error = is_error
        self.usage = usage or FakeUsage()


# ---------------------------------------------------------------------------
# launch_autonomous tests
# ---------------------------------------------------------------------------


class TestLaunchAutonomous:
    @pytest.mark.asyncio
    async def test_creates_pending_task_and_conversation(self, db_session: Session):
        """launch_autonomous should create a BackgroundTask and Conversation."""
        space = _make_space(db_session, name="Auto Space")
        agent = _make_agent(db_session, name="AutoAgent")

        conv_id, task_id = await launch_autonomous(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            goal="Build a widget",
        )

        assert conv_id is not None
        assert task_id is not None

        # Check task record
        task = background_task_service.get_background_task(db_session, task_id)
        assert task.status == "pending"
        assert task.run_type == "autonomous"
        assert task.goal == "Build a widget"
        assert task.agent_id == agent.id
        assert task.space_id == space.id
        assert task.conversation_id == conv_id

        # Check conversation
        conv = conversation_service.get_conversation(db_session, conv_id)
        assert conv.agent_id == agent.id
        assert conv.space_id == space.id
        assert "Autonomous" in conv.name

    @pytest.mark.asyncio
    async def test_duplicate_launch_rejected_409(self, db_session: Session):
        """Second autonomous launch for the same agent should raise 409."""
        space = _make_space(db_session, name="Dup Space")
        agent = _make_agent(db_session, name="DupAgent")

        # First launch succeeds
        await launch_autonomous(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            goal="First goal",
        )

        # Second launch should fail
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await launch_autonomous(
                db_session,
                agent_id=agent.id,
                space_id=space.id,
                goal="Second goal",
            )
        assert exc_info.value.status_code == 409
        assert "already has an active autonomous run" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_stores_budgets(self, db_session: Session):
        """launch_autonomous should store token and time budgets."""
        space = _make_space(db_session, name="Budget Space")
        agent = _make_agent(db_session, name="BudgetAgent")

        conv_id, task_id = await launch_autonomous(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            goal="Work on budget",
            token_budget=50000,
            time_budget=3600,
        )

        task = background_task_service.get_background_task(db_session, task_id)
        assert task.token_budget == 50000
        assert task.time_budget == 3600

    @pytest.mark.asyncio
    async def test_launch_without_space(self, db_session: Session):
        """launch_autonomous should work without a space_id."""
        agent = _make_agent(db_session, name="NoSpaceAgent")

        conv_id, task_id = await launch_autonomous(
            db_session,
            agent_id=agent.id,
            goal="Spaceless goal",
        )

        task = background_task_service.get_background_task(db_session, task_id)
        assert task.space_id is None


# ---------------------------------------------------------------------------
# approve_autonomous_launch tests
# ---------------------------------------------------------------------------


class TestApproveAutonomousLaunch:
    @pytest.mark.asyncio
    async def test_transitions_to_running(self, db_session: Session):
        """approve_autonomous_launch should transition task from pending to running."""
        space = _make_space(db_session, name="Approve Space")
        agent = _make_agent(db_session, name="ApproveAgent")

        conv_id, task_id = await launch_autonomous(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            goal="Approved goal",
        )

        # Build a fake SDK module
        fake_sdk = types.ModuleType("claude_agent_sdk")

        async def _fake_query_goal_complete(*args, **kwargs):
            yield FakeResultMessage(
                result='[{"title": "Step 1", "status": "pending"}]\nGOAL_COMPLETE',
                usage=FakeUsage(),
            )

        fake_sdk.query = _fake_query_goal_complete
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = MagicMock

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch(
                "backend.openloop.agents.agent_runner._new_db_session",
                return_value=_NoCloseSession(db_session),
            ),
            patch(
                "backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                return_value={"name": "test_server"},
            ),
            patch(
                "backend.openloop.agents.agent_runner.context_assembler"
            ) as mock_ctx,
            patch(
                "backend.openloop.agents.event_bus.event_bus",
            ) as mock_bus,
        ):
            mock_ctx.assemble_context.return_value = "System prompt"
            mock_bus.publish = AsyncMock()
            mock_bus.publish_to = AsyncMock()

            await approve_autonomous_launch(db_session, task_id=task_id)

            # Give the fire-and-forget task time to complete
            await asyncio.sleep(0.2)

        # Task should be completed (GOAL_COMPLETE was in the response)
        db_session.expire_all()
        task = background_task_service.get_background_task(db_session, task_id)
        assert task.status == "completed"

    @pytest.mark.asyncio
    async def test_rejects_non_pending_task(self, db_session: Session):
        """approve_autonomous_launch should reject a non-pending task."""
        space = _make_space(db_session, name="Reject Space")
        agent = _make_agent(db_session, name="RejectAgent")

        conv_id, task_id = await launch_autonomous(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            goal="Reject goal",
        )

        # Force task to running
        background_task_service.update_background_task(db_session, task_id, status="running")

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await approve_autonomous_launch(db_session, task_id=task_id)
        assert exc_info.value.status_code == 409

    @pytest.mark.asyncio
    async def test_rejects_non_autonomous_task(self, db_session: Session):
        """approve_autonomous_launch should reject a non-autonomous task."""
        agent = _make_agent(db_session, name="NonAutoAgent")

        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Regular task",
            run_type="task",
            status="pending",
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await approve_autonomous_launch(db_session, task_id=task.id)
        assert exc_info.value.status_code == 422


# ---------------------------------------------------------------------------
# Task list extraction tests
# ---------------------------------------------------------------------------


class TestExtractTaskListJson:
    def test_extracts_from_code_block(self):
        text = 'Here is my plan:\n```json\n[{"title": "Step 1", "status": "pending"}, {"title": "Step 2", "status": "pending"}]\n```'
        result = _extract_task_list_json(text)
        assert result is not None
        assert len(result) == 2
        assert result[0]["title"] == "Step 1"

    def test_extracts_bare_json_array(self):
        text = 'My plan: [{"title": "Do thing", "status": "pending"}]'
        result = _extract_task_list_json(text)
        assert result is not None
        assert len(result) == 1

    def test_returns_none_for_no_json(self):
        text = "This is just text with no JSON."
        result = _extract_task_list_json(text)
        assert result is None

    def test_returns_none_for_non_task_array(self):
        text = 'Some array: ["a", "b", "c"]'
        result = _extract_task_list_json(text)
        assert result is None

    def test_extracts_from_multiline_code_block(self):
        text = """Here's what I'll do:
```json
[
  {"title": "Research", "status": "pending"},
  {"title": "Implement", "status": "pending"},
  {"title": "Test", "status": "pending"}
]
```
Let me start."""
        result = _extract_task_list_json(text)
        assert result is not None
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Task list stored after first turn test
# ---------------------------------------------------------------------------


class TestAutonomousTaskList:
    @pytest.mark.asyncio
    async def test_task_list_stored_after_first_turn(self, db_session: Session):
        """After approve + first turn, task list should be stored on BackgroundTask."""
        space = _make_space(db_session, name="TaskList Space")
        agent = _make_agent(db_session, name="TaskListAgent")

        conv_id, task_id = await launch_autonomous(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            goal="Build features",
        )

        task_list_json = json.dumps([
            {"title": "Design", "status": "pending"},
            {"title": "Build", "status": "pending"},
            {"title": "Ship", "status": "pending"},
        ])
        first_turn_response = f"Here's my plan:\n```json\n{task_list_json}\n```\nGOAL_COMPLETE"

        fake_sdk = types.ModuleType("claude_agent_sdk")

        async def _fake_query(*args, **kwargs):
            yield FakeResultMessage(
                result=first_turn_response,
                usage=FakeUsage(),
            )

        fake_sdk.query = _fake_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = MagicMock

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch(
                "backend.openloop.agents.agent_runner._new_db_session",
                return_value=_NoCloseSession(db_session),
            ),
            patch(
                "backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                return_value={"name": "test_server"},
            ),
            patch(
                "backend.openloop.agents.agent_runner.context_assembler"
            ) as mock_ctx,
            patch(
                "backend.openloop.agents.event_bus.event_bus",
            ) as mock_bus,
        ):
            mock_ctx.assemble_context.return_value = "System prompt"
            mock_bus.publish = AsyncMock()
            mock_bus.publish_to = AsyncMock()

            await approve_autonomous_launch(db_session, task_id=task_id)
            await asyncio.sleep(0.2)

        db_session.expire_all()
        task = background_task_service.get_background_task(db_session, task_id)
        assert task.task_list is not None
        assert len(task.task_list) == 3
        assert task.total_count == 3
        assert task.task_list_version == 1


# ---------------------------------------------------------------------------
# update_task_list MCP tool tests
# ---------------------------------------------------------------------------


class TestUpdateTaskListMCPTool:
    @pytest.mark.asyncio
    async def test_full_replacement(self, db_session: Session):
        """update_task_list with full replacement should update task list."""
        from backend.openloop.agents.mcp_tools import update_task_list

        agent = _make_agent(db_session, name="ToolAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Test task",
            run_type="autonomous",
            status="running",
            task_list=[{"title": "A", "status": "pending"}],
        )

        new_list = json.dumps([
            {"title": "A", "status": "done"},
            {"title": "B", "status": "pending"},
        ])

        result_str = await update_task_list(
            updates=new_list,
            _db=db_session,
            _agent_id=agent.id,
            _background_task_id=task.id,
        )

        result = json.loads(result_str)
        assert "is_error" not in result
        data = result["result"]
        assert data["completed_count"] == 1
        assert data["total_count"] == 2
        assert data["task_list_version"] == 1

        # Verify DB
        db_session.expire_all()
        updated_task = background_task_service.get_background_task(db_session, task.id)
        assert updated_task.completed_count == 1
        assert updated_task.total_count == 2

    @pytest.mark.asyncio
    async def test_operational_updates(self, db_session: Session):
        """update_task_list with operations should apply changes."""
        from backend.openloop.agents.mcp_tools import update_task_list

        agent = _make_agent(db_session, name="OpAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Op task",
            run_type="autonomous",
            status="running",
            task_list=[
                {"title": "X", "status": "pending"},
                {"title": "Y", "status": "pending"},
            ],
        )

        ops = json.dumps([
            {"action": "complete", "index": 0},
            {"action": "add", "title": "Z"},
        ])

        result_str = await update_task_list(
            updates=ops,
            _db=db_session,
            _agent_id=agent.id,
            _background_task_id=task.id,
        )

        result = json.loads(result_str)
        data = result["result"]
        assert data["completed_count"] == 1
        assert data["total_count"] == 3

    @pytest.mark.asyncio
    async def test_requires_background_task_id(self, db_session: Session):
        """update_task_list should fail without a background_task_id."""
        from backend.openloop.agents.mcp_tools import update_task_list

        result_str = await update_task_list(
            updates='[{"title": "A", "status": "done"}]',
            _db=db_session,
        )

        result = json.loads(result_str)
        assert result["is_error"] is True
        assert "requires a background task" in result["error"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_json(self, db_session: Session):
        """update_task_list should reject invalid JSON."""
        from backend.openloop.agents.mcp_tools import update_task_list

        agent = _make_agent(db_session, name="BadJsonAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Bad json task",
            run_type="autonomous",
            status="running",
        )

        result_str = await update_task_list(
            updates="not json",
            _db=db_session,
            _background_task_id=task.id,
        )

        result = json.loads(result_str)
        assert result["is_error"] is True


# ---------------------------------------------------------------------------
# Pause / Resume tests
# ---------------------------------------------------------------------------


class TestPauseResume:
    @pytest.mark.asyncio
    async def test_pause_sets_status(self, db_session: Session):
        """pause_autonomous should add task to paused set."""
        agent = _make_agent(db_session, name="PauseAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Pause test",
            run_type="autonomous",
            status="running",
        )

        await pause_autonomous(db_session, task_id=task.id)
        assert task.id in _paused_tasks

    @pytest.mark.asyncio
    async def test_pause_pending_marks_paused(self, db_session: Session):
        """pause_autonomous on a pending task should mark it paused immediately."""
        agent = _make_agent(db_session, name="PausePendAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Pending pause",
            run_type="autonomous",
            status="pending",
        )

        await pause_autonomous(db_session, task_id=task.id)
        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "paused"

    @pytest.mark.asyncio
    async def test_resume_removes_from_paused(self, db_session: Session):
        """resume_autonomous should remove task from paused set."""
        agent = _make_agent(db_session, name="ResumeAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Resume test",
            run_type="autonomous",
            status="paused",
        )
        _paused_tasks.add(task.id)

        # Mock the background re-fire
        fake_sdk = types.ModuleType("claude_agent_sdk")

        async def _fake_query(*args, **kwargs):
            yield FakeResultMessage(result="GOAL_COMPLETE", usage=FakeUsage())

        fake_sdk.query = _fake_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = MagicMock

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch(
                "backend.openloop.agents.agent_runner._new_db_session",
                return_value=_NoCloseSession(db_session),
            ),
            patch(
                "backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                return_value={"name": "test_server"},
            ),
            patch(
                "backend.openloop.agents.agent_runner.context_assembler"
            ) as mock_ctx,
            patch(
                "backend.openloop.agents.event_bus.event_bus",
            ) as mock_bus,
        ):
            mock_ctx.assemble_context.return_value = "System prompt"
            mock_bus.publish = AsyncMock()
            mock_bus.publish_to = AsyncMock()

            await resume_autonomous(db_session, task_id=task.id)

        assert task.id not in _paused_tasks
        db_session.expire_all()
        updated = background_task_service.get_background_task(db_session, task.id)
        assert updated.status == "running"

    @pytest.mark.asyncio
    async def test_pause_rejects_non_autonomous(self, db_session: Session):
        """pause_autonomous should reject non-autonomous tasks."""
        agent = _make_agent(db_session, name="NonAutoPauseAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Regular task",
            run_type="task",
            status="running",
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await pause_autonomous(db_session, task_id=task.id)
        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_resume_rejects_non_paused(self, db_session: Session):
        """resume_autonomous should reject a task that isn't paused."""
        agent = _make_agent(db_session, name="NonPausedAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Not paused",
            run_type="autonomous",
            status="running",
        )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await resume_autonomous(db_session, task_id=task.id)
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# GOAL_COMPLETE stops the run
# ---------------------------------------------------------------------------


class TestGoalComplete:
    @pytest.mark.asyncio
    async def test_goal_complete_stops_run(self, db_session: Session):
        """Agent response containing GOAL_COMPLETE should stop the autonomous run."""
        space = _make_space(db_session, name="Complete Space")
        agent = _make_agent(db_session, name="CompleteAgent")

        conv_id, task_id = await launch_autonomous(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            goal="Finish quick",
        )

        fake_sdk = types.ModuleType("claude_agent_sdk")

        async def _fake_query(*args, **kwargs):
            yield FakeResultMessage(
                result="All done! GOAL_COMPLETE",
                usage=FakeUsage(),
            )

        fake_sdk.query = _fake_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = MagicMock

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch(
                "backend.openloop.agents.agent_runner._new_db_session",
                return_value=_NoCloseSession(db_session),
            ),
            patch(
                "backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                return_value={"name": "test_server"},
            ),
            patch(
                "backend.openloop.agents.agent_runner.context_assembler"
            ) as mock_ctx,
            patch(
                "backend.openloop.agents.event_bus.event_bus",
            ) as mock_bus,
        ):
            mock_ctx.assemble_context.return_value = "System prompt"
            mock_bus.publish = AsyncMock()
            mock_bus.publish_to = AsyncMock()

            await approve_autonomous_launch(db_session, task_id=task_id)
            await asyncio.sleep(0.2)

        db_session.expire_all()
        task = background_task_service.get_background_task(db_session, task_id)
        assert task.status == "completed"
        assert task.run_summary is not None

        # Should have published goal_complete event
        # (verified by mock_bus.publish calls)


# ---------------------------------------------------------------------------
# PersistentData extractor tests
# ---------------------------------------------------------------------------


class TestPersistentDataExtractor:
    def test_extractor_registered(self):
        """The autonomous task list extractor should be registered."""
        # The extractor is registered at module load time
        from backend.openloop.agents.agent_runner import _extract_autonomous_task_list

        assert _extract_autonomous_task_list in _persistent_data_extractors

    def test_extractor_returns_task_list(self, db_session: Session):
        """PersistentData extractor should return task list from DB."""
        from backend.openloop.agents.agent_runner import _extract_autonomous_task_list

        agent = _make_agent(db_session, name="ExtractorAgent")
        task_list = [
            {"title": "A", "status": "done"},
            {"title": "B", "status": "pending"},
        ]
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Extract goal",
            run_type="autonomous",
            status="running",
            goal="Extract goal",
            task_list=task_list,
        )
        background_task_service.update_background_task(
            db_session, task.id,
            task_list_version=2,
            completed_count=1,
            total_count=2,
        )

        with patch(
            "backend.openloop.agents.agent_runner._new_db_session",
            return_value=_NoCloseSession(db_session),
        ):
            result = _extract_autonomous_task_list("Extract goal", [])

        assert "task_list" in result
        assert len(result["task_list"]) == 2
        assert result["task_list_version"] == 2
        assert result["completed_count"] == 1
        assert result["total_count"] == 2

    def test_extractor_returns_empty_for_no_match(self, db_session: Session):
        """PersistentData extractor should return empty dict if no matching task."""
        from backend.openloop.agents.agent_runner import _extract_autonomous_task_list

        with patch(
            "backend.openloop.agents.agent_runner._new_db_session",
            return_value=_NoCloseSession(db_session),
        ):
            result = _extract_autonomous_task_list("Nonexistent goal", [])

        assert result == {}


# ---------------------------------------------------------------------------
# SSE event tests
# ---------------------------------------------------------------------------


class TestAutonomousProgressEvent:
    @pytest.mark.asyncio
    async def test_progress_event_published(self, db_session: Session):
        """autonomous_progress SSE event should be published after each turn."""
        space = _make_space(db_session, name="SSE Space")
        agent = _make_agent(db_session, name="SSEAgent")

        conv_id, task_id = await launch_autonomous(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            goal="SSE test",
        )

        fake_sdk = types.ModuleType("claude_agent_sdk")

        async def _fake_query(*args, **kwargs):
            yield FakeResultMessage(
                result="Working... GOAL_COMPLETE",
                usage=FakeUsage(),
            )

        fake_sdk.query = _fake_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = MagicMock

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch(
                "backend.openloop.agents.agent_runner._new_db_session",
                return_value=_NoCloseSession(db_session),
            ),
            patch(
                "backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                return_value={"name": "test_server"},
            ),
            patch(
                "backend.openloop.agents.agent_runner.context_assembler"
            ) as mock_ctx,
            patch(
                "backend.openloop.agents.event_bus.event_bus",
            ) as mock_bus,
        ):
            mock_ctx.assemble_context.return_value = "System prompt"
            mock_bus.publish = AsyncMock()
            mock_bus.publish_to = AsyncMock()

            await approve_autonomous_launch(db_session, task_id=task_id)
            await asyncio.sleep(0.2)

        # Check that autonomous_progress was published
        progress_calls = [
            call
            for call in mock_bus.publish.call_args_list
            if call.args and isinstance(call.args[0], dict)
            and call.args[0].get("type") == "autonomous_progress"
        ]
        assert len(progress_calls) >= 1

        # Check that goal_complete was published
        complete_calls = [
            call
            for call in mock_bus.publish.call_args_list
            if call.args and isinstance(call.args[0], dict)
            and call.args[0].get("type") == "goal_complete"
        ]
        assert len(complete_calls) == 1


# ---------------------------------------------------------------------------
# API route tests
# ---------------------------------------------------------------------------


class TestAPIRoutes:
    def test_launch_autonomous_route(self, client, db_session: Session):
        """POST /agents/{id}/autonomous should create a pending task."""
        space = _make_space(db_session, name="API Space")
        agent = _make_agent(db_session, name="APIAgent")

        with patch(
            "backend.openloop.agents.agent_runner._check_concurrency",
        ):
            resp = client.post(
                f"/api/v1/agents/{agent.id}/autonomous",
                json={"goal": "API test goal"},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert "conversation_id" in data
        assert "task_id" in data

    def test_get_task_list_route(self, client, db_session: Session):
        """GET /background-tasks/{id}/task-list should return task list."""
        agent = _make_agent(db_session, name="ListAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="List test",
            run_type="autonomous",
            status="running",
            task_list=[{"title": "A", "status": "pending"}],
        )
        background_task_service.update_background_task(
            db_session, task.id,
            task_list_version=1,
            total_count=1,
        )

        resp = client.get(f"/api/v1/background-tasks/{task.id}/task-list")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_count"] == 1
        assert len(data["task_list"]) == 1

    def test_update_task_list_route(self, client, db_session: Session):
        """PATCH /background-tasks/{id}/task-list should update task list."""
        agent = _make_agent(db_session, name="PatchAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Patch test",
            run_type="autonomous",
            status="running",
        )

        resp = client.patch(
            f"/api/v1/background-tasks/{task.id}/task-list",
            json={"task_list": [
                {"title": "X", "status": "done"},
                {"title": "Y", "status": "pending"},
            ]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed_count"] == 1
        assert data["total_count"] == 2
        assert data["task_list_version"] == 1

    def test_pause_route(self, client, db_session: Session):
        """POST /background-tasks/{id}/pause should pause the task."""
        agent = _make_agent(db_session, name="PauseRouteAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Pause route test",
            run_type="autonomous",
            status="running",
        )

        resp = client.post(f"/api/v1/background-tasks/{task.id}/pause")
        assert resp.status_code == 204
        assert task.id in _paused_tasks

    def test_resume_rejects_non_paused(self, client, db_session: Session):
        """POST /background-tasks/{id}/resume should reject a non-paused task."""
        agent = _make_agent(db_session, name="ResumeRouteAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="Resume route test",
            run_type="autonomous",
            status="running",
        )

        resp = client.post(f"/api/v1/background-tasks/{task.id}/resume")
        assert resp.status_code == 409
