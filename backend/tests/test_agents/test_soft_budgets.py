"""Tests for Phase 8.6b: Soft budgets + smart continuation prompts.

Tests budget enforcement (token + time), completion signal detection,
budget-exhausted final turn, continuation prompt content, compaction
integration, default budgets, and MAX_TURNS safety limit.

Mocks claude_agent_sdk to avoid real SDK calls.
"""

from __future__ import annotations

import types
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.agent_runner import (
    BUDGET_EXHAUSTED_PROMPT,
    DEFAULT_TIME_BUDGET,
    MAX_TURNS,
    _build_continuation_prompt,
    _check_budget_exhausted,
    _format_time_remaining,
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


class _NoCloseSession:
    """Wrapper around a SQLAlchemy Session that intercepts close().

    Used in tests where _run_background_task calls db.close() in its finally
    block, which would detach the test session and break subsequent assertions.
    """

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


async def _fake_query_task_complete(*args, **kwargs):
    """Async generator that yields TASK_COMPLETE immediately."""
    yield FakeResultMessage(
        result="Done. TASK_COMPLETE",
        usage=FakeUsage(input_tokens=200, output_tokens=100),
    )


async def _fake_query_goal_complete(*args, **kwargs):
    """Async generator that yields GOAL_COMPLETE immediately."""
    yield FakeResultMessage(
        result="All goals achieved. GOAL_COMPLETE",
        usage=FakeUsage(input_tokens=200, output_tokens=100),
    )


async def _fake_query_working(*args, **kwargs):
    """Async generator that yields a working (non-complete) response."""
    yield FakeResultMessage(
        result="Working on step. Made progress on the analysis.",
        usage=FakeUsage(input_tokens=150, output_tokens=75),
    )


async def _fake_query_budget_summary(*args, **kwargs):
    """Async generator that yields a budget-wrap-up response."""
    yield FakeResultMessage(
        result="Budget exhausted. Summary: completed 3 of 5 items. TASK_COMPLETE",
        usage=FakeUsage(input_tokens=100, output_tokens=50),
    )


def _build_fake_sdk(query_fn=None):
    """Build a fake claude_agent_sdk module with the given query function."""
    fake_sdk = types.ModuleType("claude_agent_sdk")
    fake_sdk.query = query_fn or _fake_query_task_complete
    fake_sdk.ClaudeAgentOptions = MagicMock()
    fake_sdk.ResultMessage = FakeResultMessage
    fake_sdk.StreamEvent = type("FakeStreamEvent", (), {})
    return fake_sdk


# ===================================================================
# _format_time_remaining tests
# ===================================================================


class TestFormatTimeRemaining:
    def test_zero(self):
        assert _format_time_remaining(0) == "0m"

    def test_negative(self):
        assert _format_time_remaining(-100) == "0m"

    def test_minutes_only(self):
        assert _format_time_remaining(1800) == "30m"

    def test_hours_and_minutes(self):
        result = _format_time_remaining(5400)  # 1h 30m
        assert result == "1h 30m"

    def test_exact_hours(self):
        result = _format_time_remaining(7200)  # 2h 0m
        assert result == "2h 0m"

    def test_rounds_up_minutes(self):
        result = _format_time_remaining(61)  # 1m 1s → rounds to 2m
        assert result == "2m"


# ===================================================================
# _check_budget_exhausted tests
# ===================================================================


class TestCheckBudgetExhausted:
    def test_no_budgets_set_uses_default_time(self, db_session: Session):
        """With no explicit budgets, default 4h time budget applies."""
        agent = _make_agent(db_session, name="NoBudgetAgent")
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )
        space = _make_space(db_session, name="NoBudgetSpace")
        conv = _make_conversation(db_session, space.id, agent.id)

        # started_at is recent, so budget should NOT be exhausted
        exhausted, reason = _check_budget_exhausted(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            started_at=datetime.now(UTC),
        )
        assert exhausted is False
        assert reason is None

    def test_token_budget_exhausted(self, db_session: Session):
        """Token budget triggers when total tokens exceed budget."""
        agent = _make_agent(db_session, name="TokenExAgent")
        space = _make_space(db_session, name="TokenExSpace")
        conv = _make_conversation(db_session, space.id, agent.id)

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )
        task.token_budget = 500
        db_session.commit()

        # Add tokens exceeding budget
        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="msg1",
            input_tokens=300,
            output_tokens=250,
        )

        exhausted, reason = _check_budget_exhausted(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            started_at=datetime.now(UTC),
        )
        assert exhausted is True
        assert "token budget exhausted" in reason

    def test_token_budget_not_exhausted(self, db_session: Session):
        """Token budget doesn't trigger when under limit."""
        agent = _make_agent(db_session, name="TokenOkAgent")
        space = _make_space(db_session, name="TokenOkSpace")
        conv = _make_conversation(db_session, space.id, agent.id)

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )
        task.token_budget = 10000
        db_session.commit()

        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="msg1",
            input_tokens=100,
            output_tokens=50,
        )

        exhausted, reason = _check_budget_exhausted(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            started_at=datetime.now(UTC),
        )
        assert exhausted is False

    def test_time_budget_exhausted(self, db_session: Session):
        """Time budget triggers when elapsed time exceeds budget."""
        agent = _make_agent(db_session, name="TimeExAgent")
        space = _make_space(db_session, name="TimeExSpace")
        conv = _make_conversation(db_session, space.id, agent.id)

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test", time_budget=60
        )

        # Started 120 seconds ago → well past 60s budget
        exhausted, reason = _check_budget_exhausted(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            started_at=datetime.now(UTC) - timedelta(seconds=120),
        )
        assert exhausted is True
        assert "time budget exhausted" in reason

    def test_time_budget_not_exhausted(self, db_session: Session):
        """Time budget doesn't trigger when under limit."""
        agent = _make_agent(db_session, name="TimeOkAgent")
        space = _make_space(db_session, name="TimeOkSpace")
        conv = _make_conversation(db_session, space.id, agent.id)

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test", time_budget=3600
        )

        exhausted, reason = _check_budget_exhausted(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            started_at=datetime.now(UTC) - timedelta(seconds=10),
        )
        assert exhausted is False

    def test_default_time_budget_value(self):
        """Default time budget is 14400 seconds (4 hours)."""
        assert DEFAULT_TIME_BUDGET == 14400


# ===================================================================
# _build_continuation_prompt tests
# ===================================================================


class TestBuildContinuationPrompt:
    def test_basic_non_autonomous(self, db_session: Session):
        """Non-autonomous tasks get a simple continuation prompt."""
        agent = _make_agent(db_session, name="BasicPromptAgent")
        space = _make_space(db_session, name="BasicPromptSpace")
        conv = _make_conversation(db_session, space.id, agent.id)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=5,
            started_at=datetime.now(UTC),
        )

        assert "Turn 5." in prompt
        assert "Continue working on the task." in prompt
        assert "TASK_COMPLETE" in prompt
        assert "GOAL_COMPLETE" in prompt

    def test_includes_budget_remaining(self, db_session: Session):
        """Prompt includes time remaining info."""
        agent = _make_agent(db_session, name="BudgetPromptAgent")
        space = _make_space(db_session, name="BudgetPromptSpace")
        conv = _make_conversation(db_session, space.id, agent.id)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test", time_budget=7200
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=3,
            started_at=datetime.now(UTC),
        )

        # Should include time remaining
        assert "remaining" in prompt
        assert "Budget:" in prompt

    def test_includes_token_budget_remaining(self, db_session: Session):
        """When token_budget is set, prompt includes tokens remaining."""
        agent = _make_agent(db_session, name="TokBudgetPromptAgent")
        space = _make_space(db_session, name="TokBudgetPromptSpace")
        conv = _make_conversation(db_session, space.id, agent.id)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )
        task.token_budget = 50000
        db_session.commit()

        # Add some token usage
        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="work",
            input_tokens=5000,
            output_tokens=2000,
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=4,
            started_at=datetime.now(UTC),
        )

        assert "tokens remaining" in prompt
        assert "43,000" in prompt  # 50000 - 7000

    def test_includes_compaction_note(self, db_session: Session):
        """After compaction, prompt includes a compaction note."""
        agent = _make_agent(db_session, name="CompNoteAgent")
        space = _make_space(db_session, name="CompNoteSpace")
        conv = _make_conversation(db_session, space.id, agent.id)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=10,
            started_at=datetime.now(UTC),
            compacted=True,
            compaction_summary="Completed initial analysis and generated report draft.",
        )

        assert "Context was compacted" in prompt
        assert "older turns have been summarized" in prompt
        assert "Completed initial analysis" in prompt

    def test_compaction_note_without_summary(self, db_session: Session):
        """Compaction note works even if no summary provided."""
        agent = _make_agent(db_session, name="CompNoSumAgent")
        space = _make_space(db_session, name="CompNoSumSpace")
        conv = _make_conversation(db_session, space.id, agent.id)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=10,
            started_at=datetime.now(UTC),
            compacted=True,
        )

        assert "Context was compacted" in prompt
        assert "Summary of prior work" not in prompt

    def test_no_compaction_note_when_not_compacted(self, db_session: Session):
        """No compaction note when compacted=False."""
        agent = _make_agent(db_session, name="NoCompAgent")
        space = _make_space(db_session, name="NoCompSpace")
        conv = _make_conversation(db_session, space.id, agent.id)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )

        prompt = _build_continuation_prompt(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            turn=5,
            started_at=datetime.now(UTC),
            compacted=False,
        )

        assert "compacted" not in prompt.lower()


# ===================================================================
# MAX_TURNS safety limit
# ===================================================================


class TestMaxTurnsSafetyLimit:
    def test_max_turns_is_large(self):
        """MAX_TURNS is raised to a large safety value (not 20)."""
        assert MAX_TURNS >= 200
        assert MAX_TURNS == 500


# ===================================================================
# Completion signal detection tests
# ===================================================================


class TestCompletionSignals:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context",
           return_value=10000)
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_task_complete_detected(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        db_session: Session,
    ):
        """TASK_COMPLETE in response triggers clean completion (backward compat)."""
        space = _make_space(db_session, name="TCDetect")
        agent = _make_agent(db_session, name="TCDetectAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = _build_fake_sdk(_fake_query_task_complete)

        from backend.openloop.agents import agent_runner

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Simple task"
        )
        conv = _make_conversation(db_session, space.id, agent.id)

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
                instruction="Simple task",
                space_id=space.id,
            )

        db_session.refresh(task)
        assert task.status == "completed"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context",
           return_value=10000)
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_goal_complete_detected(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        db_session: Session,
    ):
        """GOAL_COMPLETE in response triggers clean completion."""
        space = _make_space(db_session, name="GCDetect")
        agent = _make_agent(db_session, name="GCDetectAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = _build_fake_sdk(_fake_query_goal_complete)

        from backend.openloop.agents import agent_runner

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Goal task"
        )
        conv = _make_conversation(db_session, space.id, agent.id)

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
                instruction="Goal task",
                space_id=space.id,
            )

        db_session.refresh(task)
        assert task.status == "completed"


# ===================================================================
# Budget enforcement in the turn loop
# ===================================================================


class TestBudgetEnforcementInLoop:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context",
           return_value=10000)
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_runs_past_20_turns(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        db_session: Session,
    ):
        """Regression: task runs past old 20-turn cap when budget allows."""
        space = _make_space(db_session, name="Past20")
        agent = _make_agent(db_session, name="Past20Agent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        call_count = 0
        target_turns = 25  # Past the old MAX_TURNS=20

        async def _counting_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count >= target_turns:
                yield FakeResultMessage(
                    result="Done. TASK_COMPLETE",
                    usage=FakeUsage(input_tokens=100, output_tokens=50),
                )
            else:
                yield FakeResultMessage(
                    result="Working on step.",
                    usage=FakeUsage(input_tokens=100, output_tokens=50),
                )

        fake_sdk = _build_fake_sdk(_counting_query)

        from backend.openloop.agents import agent_runner

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Long task"
        )
        conv = _make_conversation(db_session, space.id, agent.id)

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
                instruction="Long task",
                space_id=space.id,
            )

        assert call_count >= target_turns
        db_session.refresh(task)
        assert task.status == "completed"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context",
           return_value=10000)
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_time_budget_stops_task(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        db_session: Session,
    ):
        """Time budget exhaustion gives agent final turn then stops."""
        space = _make_space(db_session, name="TimeStop")
        agent = _make_agent(db_session, name="TimeStopAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        call_count = 0

        async def _query_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield FakeResultMessage(
                result="Working. Still in progress.",
                usage=FakeUsage(input_tokens=100, output_tokens=50),
            )

        fake_sdk = _build_fake_sdk(_query_fn)

        from backend.openloop.agents import agent_runner

        # Create task with very short time budget (1 second)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Timed task",
            time_budget=1,
        )
        # Set started_at to 10 seconds ago so budget is already exhausted
        task.started_at = datetime.now(UTC) - timedelta(seconds=10)
        db_session.commit()

        conv = _make_conversation(db_session, space.id, agent.id)

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
                instruction="Timed task",
                space_id=space.id,
            )

        # Should have run 1 normal turn + 1 final (budget exhausted) turn = 2 total
        assert call_count == 2
        db_session.refresh(task)
        assert task.status == "completed"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context",
           return_value=10000)
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_token_budget_stops_task(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        db_session: Session,
    ):
        """Token budget exhaustion gives agent final turn then stops."""
        space = _make_space(db_session, name="TokenStop")
        agent = _make_agent(db_session, name="TokenStopAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        call_count = 0

        async def _query_fn(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Each turn uses 150+75=225 tokens
            yield FakeResultMessage(
                result="Working on analysis.",
                usage=FakeUsage(input_tokens=150, output_tokens=75),
            )

        fake_sdk = _build_fake_sdk(_query_fn)

        from backend.openloop.agents import agent_runner

        # Token budget of 300 — will be exceeded after first turn (225 tokens)
        # Wait: _sum_conversation_tokens reads from DB, and add_message stores after
        # each turn. First turn: 225 tokens stored → still under 300.
        # Second turn: 225 more → 450 > 300 → budget exhausted.
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Token task",
        )
        task.token_budget = 300
        db_session.commit()

        conv = _make_conversation(db_session, space.id, agent.id)

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
                instruction="Token task",
                space_id=space.id,
            )

        # Turn 1: 225 tokens (under 300) → continues
        # Turn 2: 225 more → 450 total (over 300) → budget exhausted → final turn
        # So call_count = 2 normal turns + 1 final turn = 3
        assert call_count == 3
        db_session.refresh(task)
        assert task.status == "completed"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context",
           return_value=10000)
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_budget_exhausted_message_sent(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        db_session: Session,
    ):
        """When budget exhausted, the BUDGET_EXHAUSTED_PROMPT is sent as the final turn."""
        space = _make_space(db_session, name="BudgetMsg")
        agent = _make_agent(db_session, name="BudgetMsgAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        prompts_received: list[str] = []

        async def _capture_query(*args, **kwargs):
            # Capture the prompt from kwargs or positional args
            prompt = kwargs.get("prompt") or (args[0] if args else "")
            prompts_received.append(str(prompt))
            yield FakeResultMessage(
                result="Working.",
                usage=FakeUsage(input_tokens=100, output_tokens=50),
            )

        fake_sdk = _build_fake_sdk(_capture_query)

        from backend.openloop.agents import agent_runner

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Budget msg task",
            time_budget=1,
        )
        task.started_at = datetime.now(UTC) - timedelta(seconds=100)
        db_session.commit()

        conv = _make_conversation(db_session, space.id, agent.id)

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
                instruction="Budget msg task",
                space_id=space.id,
            )

        # The last prompt sent should be the budget exhausted message
        # prompts_received: [task_instruction, BUDGET_EXHAUSTED_PROMPT]
        assert len(prompts_received) >= 2
        assert BUDGET_EXHAUSTED_PROMPT in prompts_received[-1]

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context",
           return_value=10000)
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_max_turns_safety_limit_stops_runaway(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        db_session: Session,
    ):
        """MAX_TURNS safety limit stops tasks that never complete and never
        exhaust budgets (shouldn't happen in practice but guards against bugs)."""
        space = _make_space(db_session, name="Runaway")
        agent = _make_agent(db_session, name="RunawayAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        call_count = 0

        async def _never_complete_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            yield FakeResultMessage(
                result="Still working...",
                usage=FakeUsage(input_tokens=10, output_tokens=5),
            )

        fake_sdk = _build_fake_sdk(_never_complete_query)

        from backend.openloop.agents import agent_runner

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Runaway task",
        )
        conv = _make_conversation(db_session, space.id, agent.id)

        # Temporarily reduce MAX_TURNS for this test to avoid running 500 iterations
        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch.object(agent_runner, "_new_db_session",
                        return_value=_NoCloseSession(db_session)),
            patch("backend.openloop.agents.agent_runner._build_mcp_server_by_name",
                  return_value={"name": "test-tools"}),
            patch.object(agent_runner, "MAX_TURNS", 10),
        ):
            await agent_runner._run_background_task(
                task_id=task.id,
                conversation_id=conv.id,
                agent_id=agent.id,
                agent_name=agent.name,
                default_model="sonnet",
                instruction="Runaway task",
                space_id=space.id,
            )

        # Should have stopped at the patched MAX_TURNS
        assert call_count == 10
        db_session.refresh(task)
        # Still marked as completed (with "max turns reached" note)
        assert task.status == "completed"


# ===================================================================
# Default budgets for tasks with no explicit budget
# ===================================================================


class TestDefaultBudgets:
    def test_task_without_budgets_uses_defaults(self, db_session: Session):
        """A task with no token_budget and no time_budget uses generous defaults."""
        agent = _make_agent(db_session, name="DefaultAgent")
        space = _make_space(db_session, name="DefaultSpace")
        conv = _make_conversation(db_session, space.id, agent.id)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )

        # No token budget → no token check
        assert task.token_budget is None

        # No time budget → defaults to 14400s
        exhausted, reason = _check_budget_exhausted(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            started_at=datetime.now(UTC),
        )
        assert exhausted is False

    def test_no_token_budget_means_no_token_limit(self, db_session: Session):
        """When token_budget is None, even very high token usage doesn't trigger."""
        agent = _make_agent(db_session, name="NoLimitAgent")
        space = _make_space(db_session, name="NoLimitSpace")
        conv = _make_conversation(db_session, space.id, agent.id)
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="test"
        )

        # Add a million tokens — still no exhaustion without a budget
        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="big msg",
            input_tokens=500000,
            output_tokens=500000,
        )

        exhausted, reason = _check_budget_exhausted(
            db=db_session,
            task_id=task.id,
            conversation_id=conv.id,
            started_at=datetime.now(UTC),
        )
        assert exhausted is False


# ===================================================================
# Continuation prompt includes compaction note after compaction
# ===================================================================


class TestContinuationPromptWithCompaction:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner._run_compaction_cycle",
           new_callable=AsyncMock)
    @patch("backend.openloop.agents.agent_runner._estimate_conversation_context")
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_compaction_note_in_continuation_after_compaction(
        self,
        mock_assembler,
        mock_build_tools,
        mock_estimate,
        mock_compaction,
        db_session: Session,
    ):
        """After compaction triggers, the next continuation prompt should
        include a compaction note with the summary."""
        from backend.openloop.agents.agent_runner import CHECKPOINT_THRESHOLD, CONTEXT_WINDOW_TOKENS

        space = _make_space(db_session, name="CompNote")
        agent = _make_agent(db_session, name="CompNoteAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        # Turn 1: below threshold. Turn 2: above threshold → compaction. Turn 3: complete.
        mock_estimate.side_effect = [
            int(CONTEXT_WINDOW_TOKENS * 0.50),  # Turn 1: 50%
            int(CONTEXT_WINDOW_TOKENS * 0.75),  # Turn 2: 75% → triggers compaction
            int(CONTEXT_WINDOW_TOKENS * 0.30),  # Turn 3: after compaction
        ]

        mock_compaction.return_value = (True, "Analyzed data and drafted report.", "new-session")

        prompts_received: list[str] = []
        call_count = 0

        async def _capturing_query(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            prompt = kwargs.get("prompt") or (args[0] if args else "")
            prompts_received.append(str(prompt))
            if call_count <= 2:
                yield FakeResultMessage(
                    result="Working on analysis.",
                    session_id="fake-session-123",
                    usage=FakeUsage(input_tokens=150, output_tokens=75),
                )
            else:
                yield FakeResultMessage(
                    result="Finished. TASK_COMPLETE",
                    session_id="new-session",
                    usage=FakeUsage(input_tokens=100, output_tokens=50),
                )

        fake_sdk = _build_fake_sdk(_capturing_query)

        from backend.openloop.agents import agent_runner

        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="Compaction test"
        )
        conv = _make_conversation(db_session, space.id, agent.id)

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
                instruction="Compaction test",
                space_id=space.id,
            )

        # Turn 3 prompt (index 2) should include the compaction note
        assert len(prompts_received) >= 3
        turn_3_prompt = prompts_received[2]
        assert "compacted" in turn_3_prompt.lower()
        assert "Analyzed data and drafted report" in turn_3_prompt
