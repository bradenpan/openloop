"""Tests for Phase 8.6a: Compaction loop in agent_runner.

Tests context monitoring, PersistentData, compaction cycle triggering,
and background loop continuation after compaction.

Mocks claude_agent_sdk to avoid real SDK calls.
"""

from __future__ import annotations

import asyncio
import types
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.agent_runner import (
    CHECKPOINT_THRESHOLD,
    CONTEXT_WINDOW_TOKENS,
    PersistentData,
    _build_persistent_data,
    _run_compaction_cycle,
    register_persistent_extractor,
    _persistent_data_extractors,
)
from backend.openloop.services import (
    agent_service,
    background_task_service,
    conversation_service,
    notification_service,
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
def _clean_extractors():
    """Ensure the persistent data extractors list is clean for each test."""
    original = _persistent_data_extractors.copy()
    _persistent_data_extractors.clear()
    yield
    _persistent_data_extractors.clear()
    _persistent_data_extractors.extend(original)


class _NoCloseSession:
    """Wrapper around a SQLAlchemy Session that intercepts close().

    Used in tests where _run_background_task calls db.close() in its finally
    block, which would detach the test session and break subsequent assertions.
    """

    def __init__(self, session: Session):
        self._session = session

    def close(self):
        # Don't actually close — the test fixture handles cleanup.
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


async def _fake_query_task_complete(*args, **kwargs):
    """Async generator that yields TASK_COMPLETE immediately."""
    yield FakeResultMessage(
        result="Done. TASK_COMPLETE",
        usage=FakeUsage(input_tokens=200, output_tokens=100),
    )


async def _fake_query_working(*args, **kwargs):
    """Async generator that yields a working (non-complete) response."""
    yield FakeResultMessage(
        result="Working on step. Made progress on the analysis.",
        usage=FakeUsage(input_tokens=150, output_tokens=75),
    )


async def _fake_query_summary(*args, **kwargs):
    """Async generator that yields a summary response with instruction keywords."""
    yield FakeResultMessage(
        result=(
            "Summary: analyzed the quarterly sales data from all regions. "
            "Generated a comprehensive report with quarterly breakdowns."
        ),
        session_id="fake-session-after-compaction",
        usage=FakeUsage(input_tokens=100, output_tokens=50),
    )


# ===================================================================
# PersistentData tests
# ===================================================================


class TestPersistentData:
    def test_basic_creation(self):
        pd = PersistentData(instruction="Analyze the sales data")
        assert pd.instruction == "Analyze the sales data"
        assert pd.constraints == []
        assert pd.extra == {}

    def test_with_constraints_and_extra(self):
        pd = PersistentData(
            instruction="Build a report",
            constraints=["no external APIs", "under 1000 words"],
            extra={"priority": "high", "deadline": "tomorrow"},
        )
        assert len(pd.constraints) == 2
        assert pd.extra["priority"] == "high"

    def test_extra_is_extensible(self):
        """PersistentData.extra can hold arbitrary data for future tasks."""
        pd = PersistentData(instruction="test")
        pd.extra["task_list"] = ["item1", "item2", "item3"]
        pd.extra["progress"] = {"completed": 1, "total": 3}
        assert len(pd.extra["task_list"]) == 3
        assert pd.extra["progress"]["completed"] == 1


class TestPersistentDataExtractors:
    def test_register_and_build(self):
        """Registered extractors are called during build and merged into extra."""
        def my_extractor(instruction, turn_results):
            return {"custom_key": "custom_value", "turns_seen": len(turn_results)}

        register_persistent_extractor(my_extractor)
        pd = _build_persistent_data("Do analysis", ["turn1 result", "turn2 result"])
        assert pd.extra["custom_key"] == "custom_value"
        assert pd.extra["turns_seen"] == 2

    def test_failing_extractor_is_non_fatal(self):
        """A failing extractor should not break the build."""
        def bad_extractor(instruction, turn_results):
            raise ValueError("extractor broke")

        register_persistent_extractor(bad_extractor)
        pd = _build_persistent_data("Do work", [])
        # Should still succeed, just with empty extra
        assert pd.instruction == "Do work"
        assert pd.extra == {}

    def test_multiple_extractors_merge(self):
        """Multiple extractors merge their results."""
        register_persistent_extractor(lambda i, t: {"a": 1})
        register_persistent_extractor(lambda i, t: {"b": 2})
        pd = _build_persistent_data("test", [])
        assert pd.extra == {"a": 1, "b": 2}


# ===================================================================
# Compaction cycle tests
# ===================================================================


class TestCompactionCycle:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.flush_memory", new_callable=AsyncMock)
    @patch("backend.openloop.agents.agent_runner._build_mcp_server_by_name")
    async def test_flush_memory_called_before_summary(
        self, mock_build_mcp, mock_flush, db_session: Session
    ):
        """flush_memory must be called during compaction before summary generation."""
        space = _make_space(db_session, name="FlushFirst")
        agent = _make_agent(db_session, name="FlushFirstAgent")
        conv = _make_conversation(db_session, space.id, agent.id)
        conv.sdk_session_id = "test-session"
        db_session.commit()

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test task"
        )

        mock_build_mcp.return_value = {"name": "test-tools"}

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_summary
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            success, summary, new_sid = await _run_compaction_cycle(
                db=db_session,
                task_id=task.id,
                conversation_id=conv.id,
                agent_id=agent.id,
                agent_name="FlushFirstAgent",
                space_id=space.id,
                instruction="Analyze the quarterly sales data and generate report",
                turn_results=["step 1 done", "step 2 done"],
                sdk_session_id="test-session",
                model="claude-sonnet-4-6",
                hooks={"PreToolUse": []},
            )

        mock_flush.assert_called_once_with(db_session, conversation_id=conv.id)
        assert success is True

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.flush_memory", new_callable=AsyncMock)
    @patch("backend.openloop.agents.agent_runner._build_mcp_server_by_name")
    async def test_summary_generated_during_compaction(
        self, mock_build_mcp, mock_flush, db_session: Session
    ):
        """A checkpoint summary should be created during compaction."""
        space = _make_space(db_session, name="SummaryGen")
        agent = _make_agent(db_session, name="SummaryGenAgent")
        conv = _make_conversation(db_session, space.id, agent.id)
        conv.sdk_session_id = "test-session"
        db_session.commit()

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test task"
        )

        mock_build_mcp.return_value = {"name": "test-tools"}

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_summary
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            success, summary, new_sid = await _run_compaction_cycle(
                db=db_session,
                task_id=task.id,
                conversation_id=conv.id,
                agent_id=agent.id,
                agent_name="SummaryGenAgent",
                space_id=space.id,
                instruction="Analyze the quarterly data and generate report",
                turn_results=["step 1", "step 2"],
                sdk_session_id="test-session",
                model="claude-sonnet-4-6",
                hooks={"PreToolUse": []},
            )

        assert success is True
        assert summary is not None
        assert len(summary) > 0

        # Verify checkpoint summary was stored
        summaries = conversation_service.get_summaries(
            db_session, conversation_id=conv.id
        )
        assert len(summaries) >= 1
        assert summaries[0].is_checkpoint is True

# ===================================================================
# Background loop context monitoring tests
# ===================================================================


class TestBackgroundLoopContextMonitoring:
    """Test that context estimation runs after each turn in the background loop
    and triggers compaction when threshold is exceeded."""

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._run_compaction_cycle", new_callable=AsyncMock)
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context")
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_compaction_triggers_at_threshold(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        mock_compaction,
        db_session: Session,
    ):
        """Compaction should trigger when context exceeds 70% threshold."""
        space = _make_space(db_session, name="CompTrigger")
        agent = _make_agent(db_session, name="CompTriggerAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        # First call: below threshold. Second call: above threshold (triggers compaction).
        # Third call would be after compaction but task completes.
        mock_estimate.side_effect = [
            int(CONTEXT_WINDOW_TOKENS * 0.50),  # Turn 1: 50% — no compaction
            int(CONTEXT_WINDOW_TOKENS * 0.75),  # Turn 2: 75% — triggers compaction
        ]

        # Compaction succeeds, then task completes on next turn
        mock_compaction.return_value = (True, "Summary of work", "new-session-456")

        # Turn 1: working, Turn 2: working (triggers compaction), Turn 3: TASK_COMPLETE
        call_count = 0

        async def _fake_query_sequence(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                yield FakeResultMessage(
                    result="Working on analysis step.",
                    session_id="fake-session-123",
                    usage=FakeUsage(input_tokens=150, output_tokens=75),
                )
            else:
                yield FakeResultMessage(
                    result="All done. TASK_COMPLETE",
                    session_id="new-session-456",
                    usage=FakeUsage(input_tokens=100, output_tokens=50),
                )

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_sequence
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = type("FakeStreamEvent", (), {})

        from backend.openloop.agents import agent_runner

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch.object(agent_runner, "_new_db_session",
                        return_value=_NoCloseSession(db_session)),
            patch("backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                  return_value={"name": "test-tools"}),
        ):
            await agent_runner._run_background_task(
                task_id=background_task_service.create_background_task(
                    db_session, agent_id=agent.id, instruction="Analyze data"
                ).id,
                conversation_id=conversation_service.create_conversation(
                    db_session, agent_id=agent.id, name="BG Test", space_id=space.id
                ).id,
                agent_id=agent.id,
                agent_name=agent.name,
                default_model="sonnet",
                instruction="Analyze data",
                space_id=space.id,
            )

        # Compaction should have been called once (at turn 2 when context > 70%)
        mock_compaction.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context")
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_no_compaction_when_below_threshold(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        db_session: Session,
    ):
        """No compaction should trigger when context stays below 70%."""
        space = _make_space(db_session, name="NoComp")
        agent = _make_agent(db_session, name="NoCompAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        # Always below threshold
        mock_estimate.return_value = int(CONTEXT_WINDOW_TOKENS * 0.30)

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_task_complete
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = type("FakeStreamEvent", (), {})

        from backend.openloop.agents import agent_runner

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch.object(agent_runner, "_new_db_session",
                        return_value=_NoCloseSession(db_session)),
            patch("backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                  return_value={"name": "test-tools"}),
            patch("backend.openloop.agents.agent_runner._run_compaction_cycle",
                  new_callable=AsyncMock) as mock_compaction,
        ):
            task = background_task_service.create_background_task(
                db_session, agent_id=agent.id, instruction="Quick task"
            )
            conv = conversation_service.create_conversation(
                db_session, agent_id=agent.id, name="BG NoComp", space_id=space.id
            )

            await agent_runner._run_background_task(
                task_id=task.id,
                conversation_id=conv.id,
                agent_id=agent.id,
                agent_name=agent.name,
                default_model="sonnet",
                instruction="Quick task",
                space_id=space.id,
            )

        # Compaction should NOT have been called
        mock_compaction.assert_not_called()

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._run_compaction_cycle", new_callable=AsyncMock)
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context")
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_loop_continues_after_compaction(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        mock_compaction,
        db_session: Session,
    ):
        """After successful compaction, the loop should continue running
        (not stop at MAX_TURNS prematurely)."""
        space = _make_space(db_session, name="ContinueAfter")
        agent = _make_agent(db_session, name="ContinueAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        # Turn 1: low, Turn 2: above threshold, Turn 3: low (after compaction)
        mock_estimate.side_effect = [
            int(CONTEXT_WINDOW_TOKENS * 0.50),  # Turn 1
            int(CONTEXT_WINDOW_TOKENS * 0.75),  # Turn 2 — triggers compaction
            int(CONTEXT_WINDOW_TOKENS * 0.30),  # Turn 3 — after compaction, low
        ]

        mock_compaction.return_value = (True, "Summary", "new-session")

        # Turn 1: working, Turn 2: working, Turn 3: TASK_COMPLETE
        call_count = 0

        async def _counting_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                yield FakeResultMessage(
                    result="Making progress on analysis.",
                    session_id="fake-session-123",
                    usage=FakeUsage(input_tokens=150, output_tokens=75),
                )
            else:
                yield FakeResultMessage(
                    result="Finished everything. TASK_COMPLETE",
                    session_id="new-session",
                    usage=FakeUsage(input_tokens=100, output_tokens=50),
                )

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _counting_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = type("FakeStreamEvent", (), {})

        from backend.openloop.agents import agent_runner

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Long analysis task"
        )
        conv = conversation_service.create_conversation(
            db_session, agent_id=agent.id, name="BG Continue", space_id=space.id
        )

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch.object(agent_runner, "_new_db_session",
                        return_value=_NoCloseSession(db_session)),
            patch("backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                  return_value={"name": "test-tools"}),
        ):
            await agent_runner._run_background_task(
                task_id=task.id,
                conversation_id=conv.id,
                agent_id=agent.id,
                agent_name=agent.name,
                default_model="sonnet",
                instruction="Long analysis task",
                space_id=space.id,
            )

        # Task should have completed (not just stopped at compaction)
        db_session.refresh(task)
        assert task.status == "completed"
        # Agent ran 3 turns total (2 before compaction + 1 after)
        assert call_count == 3


# ===================================================================
# Migration / model column tests
# ===================================================================


class TestBackgroundTaskColumns:
    def test_goal_column_exists(self, db_session: Session):
        agent = _make_agent(db_session, name="GoalColAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="test",
            goal="Original goal text",
        )
        assert task.goal == "Original goal text"

    def test_time_budget_column_exists(self, db_session: Session):
        agent = _make_agent(db_session, name="TimeBudgetAgent")
        task = background_task_service.create_background_task(
            db_session,
            agent_id=agent.id,
            instruction="test",
            time_budget=14400,
        )
        assert task.time_budget == 14400

    def test_goal_and_time_budget_default_none(self, db_session: Session):
        agent = _make_agent(db_session, name="DefaultNoneAgent")
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )
        assert task.goal is None
        assert task.time_budget is None
