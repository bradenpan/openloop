"""Tests for Phase 8.4 features in agent_runner: kill switch guards and token tracking.

Mocks claude_agent_sdk to avoid real SDK calls.
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.agents.agent_runner import (
    _extract_usage,
    _sum_conversation_tokens,
    delegate_background,
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


async def _fake_query_generator(*args, **kwargs):
    """Async generator that yields a FakeResultMessage with usage data."""
    yield FakeResultMessage(usage=FakeUsage(input_tokens=150, output_tokens=75))


async def _fake_query_task_complete(*args, **kwargs):
    """Async generator that yields TASK_COMPLETE immediately."""
    yield FakeResultMessage(
        result="Done. TASK_COMPLETE",
        usage=FakeUsage(input_tokens=200, output_tokens=100),
    )


# ---------------------------------------------------------------------------
# _extract_usage tests
# ---------------------------------------------------------------------------


class TestExtractUsage:
    def test_extract_from_object(self):
        msg = FakeResultMessage(usage=FakeUsage(input_tokens=500, output_tokens=200))
        inp, out = _extract_usage(msg)
        assert inp == 500
        assert out == 200

    def test_extract_from_dict(self):
        msg = FakeResultMessage()
        msg.usage = {"input_tokens": 300, "output_tokens": 150}
        inp, out = _extract_usage(msg)
        assert inp == 300
        assert out == 150

    def test_extract_none_when_no_usage(self):
        msg = FakeResultMessage()
        msg.usage = None
        inp, out = _extract_usage(msg)
        assert inp is None
        assert out is None

    def test_extract_none_when_no_message(self):
        inp, out = _extract_usage(None)
        assert inp is None
        assert out is None


# ---------------------------------------------------------------------------
# _sum_conversation_tokens tests
# ---------------------------------------------------------------------------


class TestSumConversationTokens:
    def test_sum_empty_conversation(self, db_session: Session):
        space = _make_space(db_session, name="SumEmpty")
        agent = _make_agent(db_session, name="SumEmptyAgent")
        conv = _make_conversation(db_session, space.id, agent.id)
        total = _sum_conversation_tokens(db_session, conv.id)
        assert total == 0

    def test_sum_with_messages(self, db_session: Session):
        space = _make_space(db_session, name="SumTokens")
        agent = _make_agent(db_session, name="SumTokenAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="msg1",
            input_tokens=100,
            output_tokens=50,
        )
        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="msg2",
            input_tokens=200,
            output_tokens=100,
        )
        # Message without tokens (user message) — should contribute 0
        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="user",
            content="user msg",
        )

        total = _sum_conversation_tokens(db_session, conv.id)
        assert total == 450  # (100+50) + (200+100)


# ---------------------------------------------------------------------------
# Token extraction stores counts on messages
# ---------------------------------------------------------------------------


class TestTokenExtraction:
    def test_add_message_with_tokens(self, db_session: Session):
        """Verify conversation_service.add_message stores token counts."""
        space = _make_space(db_session, name="TokStore")
        agent = _make_agent(db_session, name="TokStoreAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        msg = conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="response",
            input_tokens=500,
            output_tokens=200,
        )

        assert msg.input_tokens == 500
        assert msg.output_tokens == 200

    def test_add_message_without_tokens(self, db_session: Session):
        """Messages without tokens should have None for token fields."""
        space = _make_space(db_session, name="TokNone")
        agent = _make_agent(db_session, name="TokNoneAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        msg = conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="user",
            content="hello",
        )

        assert msg.input_tokens is None
        assert msg.output_tokens is None


# ---------------------------------------------------------------------------
# Kill switch guard in delegate_background
# ---------------------------------------------------------------------------


class TestKillSwitchGuard:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_delegate_background_rejects_when_paused(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """delegate_background should raise 503 when system is paused."""
        space = _make_space(db_session, name="KSGuard")
        agent = _make_agent(db_session, name="KSGuardAgent")

        system_service.emergency_stop(db_session)

        with pytest.raises(HTTPException) as exc_info:
            await delegate_background(
                db_session,
                agent_id=agent.id,
                instruction="Do work",
                space_id=space.id,
            )
        assert exc_info.value.status_code == 503
        assert "paused" in exc_info.value.detail.lower()

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_delegate_background_works_when_not_paused(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """delegate_background should work normally when system is not paused."""
        space = _make_space(db_session, name="KSNotPaused")
        agent = _make_agent(db_session, name="KSNotPausedAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_task_complete
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = type("FakeStreamEvent", (), {})

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            task_id = await delegate_background(
                db_session,
                agent_id=agent.id,
                instruction="Do work",
                space_id=space.id,
            )

        assert task_id is not None
        task = background_task_service.get_background_task(db_session, task_id)
        assert task.agent_id == agent.id

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_delegate_background_works_after_resume(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """After resume, delegate_background should work again."""
        space = _make_space(db_session, name="KSResume")
        agent = _make_agent(db_session, name="KSResumeAgent")

        system_service.emergency_stop(db_session)
        system_service.resume(db_session)

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_task_complete
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = type("FakeStreamEvent", (), {})

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            task_id = await delegate_background(
                db_session,
                agent_id=agent.id,
                instruction="Do work after resume",
                space_id=space.id,
            )

        assert task_id is not None


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------


class TestTokenBudget:
    def test_background_task_has_token_budget_column(self, db_session: Session):
        """Verify token_budget column exists on BackgroundTask."""
        agent = _make_agent(db_session, name="BudgetAgent")
        task = background_task_service.create_background_task(
            db_session, agent_id=agent.id, instruction="budgeted task"
        )
        assert task.token_budget is None  # Default is None

        # Manually set budget
        task.token_budget = 10000
        db_session.commit()
        db_session.refresh(task)
        assert task.token_budget == 10000

    def test_budget_exceeded_detection(self, db_session: Session):
        """When tokens exceed budget, the total should be detectable."""
        space = _make_space(db_session, name="BudgetSpace")
        agent = _make_agent(db_session, name="BudgetDetectAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # Add messages totaling 500 tokens
        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="turn1",
            input_tokens=200,
            output_tokens=100,
        )
        conversation_service.add_message(
            db_session,
            conversation_id=conv.id,
            role="assistant",
            content="turn2",
            input_tokens=150,
            output_tokens=50,
        )

        total = _sum_conversation_tokens(db_session, conv.id)
        assert total == 500

        # Budget of 400 would be exceeded
        budget = 400
        assert total >= budget
