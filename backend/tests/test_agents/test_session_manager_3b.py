"""Tests for Phase 3b session manager safety mechanisms.

Covers: flush_memory, verify_compaction, _estimate_conversation_context,
and proactive budget enforcement.

These tests mock the Claude SDK heavily since the session manager bridges
to the external SDK.
"""

from __future__ import annotations

import logging
import types
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.session_manager import (
    CHECKPOINT_THRESHOLD,
    CONTEXT_WINDOW_TOKENS,
    FLUSH_MEMORY_PROMPT,
    SessionState,
    _clear_active_sessions,
    _estimate_conversation_context,
    _get_active_sessions,
    flush_memory,
    verify_compaction,
)
from backend.openloop.services import (
    agent_service,
    conversation_service,
    memory_service,
    space_service,
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


class FakeResultMessage:
    """Mimics claude_agent_sdk.ResultMessage."""

    def __init__(self, session_id="fake-session-123", result="OK", is_error=False):
        self.session_id = session_id
        self.result = result
        self.is_error = is_error


@pytest.fixture(autouse=True)
def _clear_sessions():
    _clear_active_sessions()
    yield
    _clear_active_sessions()


@pytest.fixture(autouse=True)
def _mock_permission_hooks():
    with patch(
        "backend.openloop.agents.session_manager._build_hooks_dict",
        return_value={"PreToolUse": []},
    ):
        yield


# ---------------------------------------------------------------------------
# flush_memory tests
# ---------------------------------------------------------------------------


class TestFlushMemory:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_sends_flush_prompt(self, mock_build_tools, db_session: Session):
        """flush_memory should send FLUSH_MEMORY_PROMPT to the SDK."""
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="FlushAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        state = SessionState(
            sdk_session_id="sess-flush-001",
            agent_id=agent.id,
            conversation_id=conv.id,
            space_id=space.id,
            status="active",
        )
        _get_active_sessions()[conv.id] = state

        captured_prompts = []

        async def _capture_query(*args, **kwargs):
            captured_prompts.append(kwargs.get("prompt") or (args[0] if args else None))
            yield FakeResultMessage()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _capture_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            await flush_memory(db_session, conversation_id=conv.id)

        assert len(captured_prompts) == 1
        assert captured_prompts[0] == FLUSH_MEMORY_PROMPT

    @pytest.mark.asyncio
    async def test_noop_without_active_session(self, db_session: Session):
        """flush_memory should do nothing if there's no active session."""
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="NoSessFlush")
        conv = _make_conversation(db_session, space.id, agent.id)

        # No active session registered — should return without error
        await flush_memory(db_session, conversation_id=conv.id)

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_catches_exceptions(self, mock_build_tools, db_session: Session):
        """flush_memory should catch and log exceptions, not raise them."""
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="ErrFlush")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        state = SessionState(
            sdk_session_id="sess-err-flush",
            agent_id=agent.id,
            conversation_id=conv.id,
            space_id=space.id,
            status="active",
        )
        _get_active_sessions()[conv.id] = state

        async def _raise_query(*args, **kwargs):
            raise RuntimeError("SDK exploded")
            yield  # noqa: B027

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _raise_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            # Should NOT raise
            await flush_memory(db_session, conversation_id=conv.id)


# ---------------------------------------------------------------------------
# verify_compaction tests
# ---------------------------------------------------------------------------


class TestVerifyCompaction:
    @pytest.mark.asyncio
    async def test_no_warnings_when_facts_in_memory(self, db_session: Session, caplog):
        """No warnings should be logged when compressed decisions exist in memory."""
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="VerifyOK")
        conv = _make_conversation(db_session, space.id, agent.id)

        # Create a memory entry covering the decision
        memory_service.create_entry(
            db_session,
            namespace=f"space:{space.id}",
            key="tech-stack",
            value="We decided to use FastAPI for the backend",
        )

        # Compressed content mentions the same decision (no extra lines that trigger patterns)
        compressed = "We decided to use FastAPI for the backend"

        with caplog.at_level(logging.WARNING, logger="backend.openloop.agents.session_manager"):
            await verify_compaction(
                db_session,
                conversation_id=conv.id,
                compressed_content=compressed,
            )

        gap_warnings = [r for r in caplog.records if "Post-compaction gap" in r.message]
        assert len(gap_warnings) == 0

    @pytest.mark.asyncio
    async def test_warnings_when_facts_missing(self, db_session: Session, caplog):
        """Warnings should be logged when decisions are NOT in memory."""
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="VerifyGap")
        conv = _make_conversation(db_session, space.id, agent.id)

        # No memory entries at all — compressed content has decisions
        compressed = "user: We decided to use GraphQL instead of REST"

        with caplog.at_level(logging.WARNING, logger="backend.openloop.agents.session_manager"):
            await verify_compaction(
                db_session,
                conversation_id=conv.id,
                compressed_content=compressed,
            )

        gap_warnings = [r for r in caplog.records if "Post-compaction gap" in r.message]
        assert len(gap_warnings) >= 1

    @pytest.mark.asyncio
    async def test_no_warnings_for_empty_content(self, db_session: Session, caplog):
        """Empty compressed content should not produce any warnings."""
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="VerifyEmpty")
        conv = _make_conversation(db_session, space.id, agent.id)

        with caplog.at_level(logging.WARNING, logger="backend.openloop.agents.session_manager"):
            await verify_compaction(
                db_session,
                conversation_id=conv.id,
                compressed_content="",
            )

        gap_warnings = [r for r in caplog.records if "Post-compaction gap" in r.message]
        assert len(gap_warnings) == 0


# ---------------------------------------------------------------------------
# _estimate_conversation_context tests
# ---------------------------------------------------------------------------


class TestEstimateConversationContext:
    def test_basic_estimate(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="EstAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # Add some messages
        conversation_service.add_message(
            db_session, conversation_id=conv.id, role="user", content="Hello world"
        )
        conversation_service.add_message(
            db_session, conversation_id=conv.id, role="assistant", content="Hi there!"
        )

        estimate = _estimate_conversation_context(db_session, conv.id, "new message")
        assert estimate > 0

    def test_includes_system_prompt_tokens(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(
            db_session,
            name="SysPromptAgent",
            description="A very long description " * 50,
        )
        conv = _make_conversation(db_session, space.id, agent.id)

        estimate = _estimate_conversation_context(db_session, conv.id, "")
        # The system prompt should contribute tokens
        assert estimate > 0

    def test_includes_message_tokens(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="MsgAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        estimate_empty = _estimate_conversation_context(db_session, conv.id, "")

        # Add messages to increase the estimate
        for i in range(10):
            conversation_service.add_message(
                db_session,
                conversation_id=conv.id,
                role="user",
                content=f"Message {i} " * 20,
            )

        estimate_with_msgs = _estimate_conversation_context(db_session, conv.id, "")
        assert estimate_with_msgs > estimate_empty

    def test_includes_pending_message(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="PendAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        short = _estimate_conversation_context(db_session, conv.id, "short")
        long = _estimate_conversation_context(db_session, conv.id, "x" * 1000)
        assert long > short


# ---------------------------------------------------------------------------
# Proactive budget enforcement (conceptual — mock heavy)
# ---------------------------------------------------------------------------


class TestProactiveBudgetEnforcement:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_flush_and_compress_called_above_threshold(
        self, mock_build_tools, db_session: Session
    ):
        """When context > 70%, flush_memory and _compress_conversation should be called."""
        space = _make_space(db_session, name="BudgetSpace")
        agent = _make_agent(db_session, name="BudgetAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        # Set up active session
        state = SessionState(
            sdk_session_id="sess-budget-001",
            agent_id=agent.id,
            conversation_id=conv.id,
            space_id=space.id,
            status="active",
        )
        _get_active_sessions()[conv.id] = state

        # Pre-save the user message (the API route does this)
        conversation_service.add_message(
            db_session, conversation_id=conv.id, role="user", content="test"
        )

        # Mock _estimate_conversation_context to return > 70% of context window
        high_utilization = int(CONTEXT_WINDOW_TOKENS * 0.80)

        fake_sdk = types.ModuleType("claude_agent_sdk")

        async def _fake_query(*args, **kwargs):
            yield FakeResultMessage(result="response")

        fake_sdk.query = _fake_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = type("FakeStreamEvent", (), {"data": {}})

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch(
                "backend.openloop.agents.session_manager._estimate_conversation_context",
                return_value=high_utilization,
            ),
            patch(
                "backend.openloop.agents.session_manager.flush_memory",
            ) as mock_flush,
            patch(
                "backend.openloop.agents.session_manager._compress_conversation",
            ) as mock_compress,
        ):
            from backend.openloop.agents.session_manager import send_message

            events = []
            async for evt in send_message(
                db_session, conversation_id=conv.id, message="test"
            ):
                events.append(evt)

            mock_flush.assert_called_once()
            mock_compress.assert_called_once()

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_no_flush_below_threshold(
        self, mock_build_tools, db_session: Session
    ):
        """When context < 70%, flush_memory should NOT be called."""
        space = _make_space(db_session, name="LowSpace")
        agent = _make_agent(db_session, name="LowAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        state = SessionState(
            sdk_session_id="sess-low-001",
            agent_id=agent.id,
            conversation_id=conv.id,
            space_id=space.id,
            status="active",
        )
        _get_active_sessions()[conv.id] = state

        conversation_service.add_message(
            db_session, conversation_id=conv.id, role="user", content="test"
        )

        low_utilization = int(CONTEXT_WINDOW_TOKENS * 0.30)

        fake_sdk = types.ModuleType("claude_agent_sdk")

        async def _fake_query(*args, **kwargs):
            yield FakeResultMessage(result="response")

        fake_sdk.query = _fake_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = type("FakeStreamEvent", (), {"data": {}})

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch(
                "backend.openloop.agents.session_manager._estimate_conversation_context",
                return_value=low_utilization,
            ),
            patch(
                "backend.openloop.agents.session_manager.flush_memory",
            ) as mock_flush,
            patch(
                "backend.openloop.agents.session_manager._compress_conversation",
            ) as mock_compress,
        ):
            from backend.openloop.agents.session_manager import send_message

            events = []
            async for evt in send_message(
                db_session, conversation_id=conv.id, message="test"
            ):
                events.append(evt)

            mock_flush.assert_not_called()
            mock_compress.assert_not_called()
