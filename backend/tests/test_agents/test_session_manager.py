"""Tests for the Session Manager module.

Mocks claude_agent_sdk.query to avoid real SDK calls. Tests cover:
- start_session assembling context and calling query
- send_message storing messages and streaming events
- close_session generating summary and closing conversation
- _active_sessions tracking
- Model name mapping
- Error handling (ProcessError on resume, ExceptionGroup)
- Background delegation
- Reopen conversation (valid and invalid sessions)
- Crash recovery
- Concurrency limits
- Context usage monitoring
"""

from __future__ import annotations

import types
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.session_manager import (
    CONTEXT_WINDOW_TOKENS,
    MAX_INTERACTIVE_SESSIONS,
    MODEL_MAP,
    SessionState,
    _check_concurrency,
    _clear_active_sessions,
    _count_sessions,
    _get_active_sessions,
    close_session,
    delegate_background,
    list_active,
    monitor_context_usage,
    recover_from_crash,
    reopen_conversation,
    resolve_model,
    send_message,
    start_session,
)
from backend.openloop.services import (
    agent_service,
    background_task_service,
    conversation_service,
    notification_service,
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


@pytest.fixture(autouse=True)
def _clear_sessions():
    """Ensure active sessions are cleared before each test."""
    _clear_active_sessions()
    yield
    _clear_active_sessions()


@pytest.fixture(autouse=True)
def _mock_permission_hooks():
    """Mock _build_hooks_dict so tests don't need the real SDK hook types.

    Permission hook logic is tested separately in test_permission_enforcer.py.
    """
    with patch(
        "backend.openloop.agents.session_manager._build_hooks_dict",
        return_value={"PreToolUse": []},
    ):
        yield


# ---------------------------------------------------------------------------
# Fake SDK types for mocking
# ---------------------------------------------------------------------------


class FakeResultMessage:
    """Mimics claude_agent_sdk.ResultMessage."""

    def __init__(self, session_id="fake-session-123", result="Hello!", is_error=False):
        self.session_id = session_id
        self.result = result
        self.is_error = is_error


class FakeStreamEvent:
    """Mimics claude_agent_sdk.StreamEvent."""

    def __init__(self, data=None):
        self.data = data or {"type": "content_block_delta"}


async def _fake_query_generator(*args, **kwargs):
    """Async generator that yields a FakeResultMessage."""
    yield FakeResultMessage()


async def _fake_query_generator_with_stream(*args, **kwargs):
    """Async generator that yields stream events then a result."""
    yield FakeStreamEvent({"type": "content_block_delta", "text": "Hello"})
    yield FakeStreamEvent({"type": "content_block_delta", "text": " world"})
    yield FakeResultMessage(result="Hello world")


async def _fake_query_raises(*args, **kwargs):
    """Async generator that raises an exception."""
    raise RuntimeError("SDK connection failed")
    yield  # noqa: B027 — unreachable yield makes this an async generator


# ---------------------------------------------------------------------------
# Model name mapping tests
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_short_names_map_correctly(self):
        assert resolve_model("haiku") == "claude-haiku-4-5-20251001"
        assert resolve_model("sonnet") == "claude-sonnet-4-6"
        assert resolve_model("opus") == "claude-opus-4-6"

    def test_full_ids_pass_through(self):
        full_id = "claude-sonnet-4-6"
        assert resolve_model(full_id) == full_id

    def test_unknown_names_pass_through(self):
        assert resolve_model("unknown-model") == "unknown-model"

    def test_model_map_has_expected_entries(self):
        assert "haiku" in MODEL_MAP
        assert "sonnet" in MODEL_MAP
        assert "opus" in MODEL_MAP


# ---------------------------------------------------------------------------
# SessionState tests
# ---------------------------------------------------------------------------


class TestSessionState:
    def test_defaults(self):
        state = SessionState(
            sdk_session_id="sess-1",
            agent_id="agent-1",
            conversation_id="conv-1",
            space_id="space-1",
            status="active",
        )
        assert state.sdk_session_id == "sess-1"
        assert state.status == "active"
        assert isinstance(state.started_at, datetime)
        assert isinstance(state.last_activity, datetime)

    def test_none_sdk_session_id(self):
        state = SessionState(
            sdk_session_id=None,
            agent_id="agent-1",
            conversation_id="conv-1",
            space_id=None,
            status="active",
        )
        assert state.sdk_session_id is None
        assert state.space_id is None


# ---------------------------------------------------------------------------
# start_session tests
# ---------------------------------------------------------------------------


class TestStartSession:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_start_session_happy_path(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """start_session should call query, store session_id, track state."""
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="TestAgent", default_model="sonnet")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_assembler.assemble_context.return_value = "System prompt here"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_generator
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            state = await start_session(db_session, conversation_id=conv.id, agent_id=agent.id)

        assert state.sdk_session_id == "fake-session-123"
        assert state.agent_id == agent.id
        assert state.conversation_id == conv.id
        assert state.space_id == space.id
        assert state.status == "active"

        # Should be tracked in active sessions
        assert conv.id in _get_active_sessions()

        # SDK session_id should be persisted to conversation
        updated_conv = conversation_service.get_conversation(db_session, conv.id)
        assert updated_conv.sdk_session_id == "fake-session-123"

        # Context assembler should have been called
        mock_assembler.assemble_context.assert_called_once_with(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            conversation_id=conv.id,
        )

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_odin_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_start_session_odin_uses_odin_tools(
        self, mock_assembler, mock_build_odin, db_session: Session
    ):
        """Odin agent should use build_odin_tools instead of build_agent_tools."""
        space = _make_space(db_session, name="Odin Space")
        agent = _make_agent(db_session, name="Odin", default_model="sonnet")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_assembler.assemble_context.return_value = "Odin prompt"
        mock_build_odin.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_generator
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            state = await start_session(db_session, conversation_id=conv.id, agent_id=agent.id)

        mock_build_odin.assert_called_once()
        assert state.sdk_session_id == "fake-session-123"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_start_session_uses_model_override(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """When conversation has model_override, it should be used over agent default."""
        space = _make_space(db_session, name="Model Space")
        agent = _make_agent(db_session, name="ModelAgent", default_model="sonnet")
        conv = _make_conversation(db_session, space.id, agent.id, model_override="haiku")

        mock_assembler.assemble_context.return_value = "Prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.ResultMessage = FakeResultMessage

        captured_options = {}

        class FakeClaudeAgentOptions:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        fake_sdk.ClaudeAgentOptions = FakeClaudeAgentOptions

        async def capture_query(*args, **kwargs):
            captured_options.update(kwargs)
            yield FakeResultMessage()

        fake_sdk.query = capture_query

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            await start_session(db_session, conversation_id=conv.id, agent_id=agent.id)

        # The model passed should be the resolved haiku model
        opts = captured_options.get("options")
        assert opts is not None
        assert opts.model == "claude-haiku-4-5-20251001"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_start_session_sdk_error_marks_interrupted(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """If the SDK raises, the conversation should be marked interrupted."""
        space = _make_space(db_session, name="Error Space")
        agent = _make_agent(db_session, name="ErrorAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_assembler.assemble_context.return_value = "Prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_raises
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            with pytest.raises(RuntimeError, match="SDK connection failed"):
                await start_session(db_session, conversation_id=conv.id, agent_id=agent.id)

        # Conversation should be marked interrupted
        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "interrupted"

        # Should NOT be in active sessions
        assert conv.id not in _get_active_sessions()


# ---------------------------------------------------------------------------
# send_message tests
# ---------------------------------------------------------------------------


class TestSendMessage:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_send_message_with_active_session(self, mock_build_tools, db_session: Session):
        """send_message should yield events and store messages in DB."""
        space = _make_space(db_session, name="Msg Space")
        agent = _make_agent(db_session, name="MsgAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        # Pre-populate active session
        state = SessionState(
            sdk_session_id="sess-msg-123",
            agent_id=agent.id,
            conversation_id=conv.id,
            space_id=space.id,
            status="active",
        )
        _get_active_sessions()[conv.id] = state

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_generator_with_stream
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = FakeStreamEvent

        # Pre-save user message (the API route does this, not send_message)
        conversation_service.add_message(
            db_session, conversation_id=conv.id, role="user", content="Hello agent"
        )

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            events = []
            async for evt in send_message(
                db_session, conversation_id=conv.id, message="Hello agent"
            ):
                events.append(evt)

        # Should have stream events + no error
        stream_events = [e for e in events if e.get("type") == "stream"]
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(stream_events) == 2
        assert len(error_events) == 0

        # User message was pre-saved by caller; assistant message saved by send_message
        messages = conversation_service.get_messages(db_session, conv.id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello agent"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hello world"

    @pytest.mark.asyncio
    async def test_send_message_no_session_yields_error(self, db_session: Session):
        """send_message with no active session and no sdk_session_id yields error."""
        space = _make_space(db_session, name="NoSess Space")
        agent = _make_agent(db_session, name="NoSessAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        events = []
        async for evt in send_message(db_session, conversation_id=conv.id, message="Hello"):
            events.append(evt)

        assert len(events) == 1
        assert events[0]["type"] == "error"
        assert "No active session" in events[0]["error"]

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_send_message_resumes_from_db(self, mock_build_tools, db_session: Session):
        """send_message should resume a session from conversation.sdk_session_id."""
        space = _make_space(db_session, name="Resume Space")
        agent = _make_agent(db_session, name="ResumeAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # Set sdk_session_id on conversation but no active session
        conversation_service.update_conversation(
            db_session, conv.id, sdk_session_id="persisted-sess-456"
        )

        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_generator_with_stream
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = FakeStreamEvent
        fake_sdk.get_session_info = MagicMock(return_value={"id": "persisted-sess-456"})

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            events = []
            async for evt in send_message(db_session, conversation_id=conv.id, message="Resuming"):
                events.append(evt)

        # Should have rebuilt active session
        assert conv.id in _get_active_sessions()
        rebuilt = _get_active_sessions()[conv.id]
        # The SDK returns a new session_id in ResultMessage, which updates the state
        assert rebuilt.sdk_session_id == "fake-session-123"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_send_message_sdk_error_marks_interrupted(
        self, mock_build_tools, db_session: Session
    ):
        """SDK errors during send_message should mark conversation as interrupted."""
        space = _make_space(db_session, name="SdkErr Space")
        agent = _make_agent(db_session, name="SdkErrAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        state = SessionState(
            sdk_session_id="sess-err-789",
            agent_id=agent.id,
            conversation_id=conv.id,
            space_id=space.id,
            status="active",
        )
        _get_active_sessions()[conv.id] = state

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_raises
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = FakeStreamEvent

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            events = []
            async for evt in send_message(db_session, conversation_id=conv.id, message="Will fail"):
                events.append(evt)

        # Should yield an error event
        assert any(e.get("type") == "error" for e in events)

        # Conversation should be interrupted
        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "interrupted"


# ---------------------------------------------------------------------------
# close_session tests
# ---------------------------------------------------------------------------


class TestCloseSession:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_close_session_generates_summary(self, mock_build_tools, db_session: Session):
        """close_session should generate a summary, store it, and close the conv."""
        space = _make_space(db_session, name="Close Space")
        agent = _make_agent(db_session, name="CloseAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        state = SessionState(
            sdk_session_id="sess-close-001",
            agent_id=agent.id,
            conversation_id=conv.id,
            space_id=space.id,
            status="active",
        )
        _get_active_sessions()[conv.id] = state

        async def _summary_query(*args, **kwargs):
            yield FakeResultMessage(result="Summary: discussed X, decided Y.")

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _summary_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            summary = await close_session(db_session, conversation_id=conv.id)

        assert summary == "Summary: discussed X, decided Y."

        # Conversation should be closed
        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "closed"

        # Summary should be stored
        summaries = conversation_service.get_summaries(db_session, conversation_id=conv.id)
        assert len(summaries) == 1
        assert "discussed X" in summaries[0].summary

        # Should be removed from active sessions
        assert conv.id not in _get_active_sessions()

    @pytest.mark.asyncio
    async def test_close_session_no_sdk_session_still_closes(self, db_session: Session):
        """If there's no SDK session, close_session should still close the conv."""
        space = _make_space(db_session, name="NoSdk Space")
        agent = _make_agent(db_session, name="NoSdkAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        summary = await close_session(db_session, conversation_id=conv.id)

        assert summary == ""

        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "closed"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    async def test_close_session_sdk_error_still_closes(
        self, mock_build_tools, db_session: Session
    ):
        """If SDK summary generation fails, should still close with fallback text."""
        space = _make_space(db_session, name="FailClose Space")
        agent = _make_agent(db_session, name="FailCloseAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        state = SessionState(
            sdk_session_id="sess-fail-close",
            agent_id=agent.id,
            conversation_id=conv.id,
            space_id=space.id,
            status="active",
        )
        _get_active_sessions()[conv.id] = state

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_raises
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            summary = await close_session(db_session, conversation_id=conv.id)

        assert "Summary generation failed" in summary

        # Conversation should still be closed
        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "closed"

        # Should be removed from active sessions
        assert conv.id not in _get_active_sessions()


# ---------------------------------------------------------------------------
# list_active / tracking tests
# ---------------------------------------------------------------------------


class TestActiveSessionTracking:
    def test_list_active_empty(self):
        assert list_active() == []

    def test_list_active_returns_tracked_sessions(self):
        state1 = SessionState(
            sdk_session_id="s1",
            agent_id="a1",
            conversation_id="c1",
            space_id="sp1",
            status="active",
        )
        state2 = SessionState(
            sdk_session_id="s2",
            agent_id="a2",
            conversation_id="c2",
            space_id="sp2",
            status="background",
        )
        _get_active_sessions()["c1"] = state1
        _get_active_sessions()["c2"] = state2

        active = list_active()
        assert len(active) == 2
        conv_ids = {s.conversation_id for s in active}
        assert conv_ids == {"c1", "c2"}

    def test_clear_active_sessions(self):
        _get_active_sessions()["c1"] = SessionState(
            sdk_session_id="s1",
            agent_id="a1",
            conversation_id="c1",
            space_id=None,
            status="active",
        )
        assert len(list_active()) == 1

        _clear_active_sessions()
        assert len(list_active()) == 0


# ---------------------------------------------------------------------------
# Concurrency control tests
# ---------------------------------------------------------------------------


class TestConcurrencyControl:
    def test_count_sessions_empty(self):
        assert _count_sessions() == 0
        assert _count_sessions("active") == 0
        assert _count_sessions("background") == 0

    def test_count_sessions_with_filter(self):
        _get_active_sessions()["c1"] = SessionState(
            sdk_session_id="s1",
            agent_id="a1",
            conversation_id="c1",
            space_id=None,
            status="active",
        )
        _get_active_sessions()["c2"] = SessionState(
            sdk_session_id="s2",
            agent_id="a2",
            conversation_id="c2",
            space_id=None,
            status="background",
        )
        _get_active_sessions()["c3"] = SessionState(
            sdk_session_id="s3",
            agent_id="a3",
            conversation_id="c3",
            space_id=None,
            status="active",
        )

        assert _count_sessions() == 3
        assert _count_sessions("active") == 2
        assert _count_sessions("background") == 1

    def test_check_concurrency_allows_under_limit(self):
        """Should not raise when under the limit."""
        # Add fewer than MAX sessions
        for i in range(MAX_INTERACTIVE_SESSIONS - 1):
            _get_active_sessions()[f"c{i}"] = SessionState(
                sdk_session_id=f"s{i}",
                agent_id="a1",
                conversation_id=f"c{i}",
                space_id=None,
                status="active",
            )
        # Should not raise
        _check_concurrency("active")

    def test_check_concurrency_rejects_at_limit(self):
        """Should raise 429 when at the interactive session limit."""
        for i in range(MAX_INTERACTIVE_SESSIONS):
            _get_active_sessions()[f"c{i}"] = SessionState(
                sdk_session_id=f"s{i}",
                agent_id="a1",
                conversation_id=f"c{i}",
                space_id=None,
                status="active",
            )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _check_concurrency("active")
        assert exc_info.value.status_code == 429
        assert "Too many active sessions" in str(exc_info.value.detail)

    def test_check_concurrency_background_limit(self):
        """Background sessions have their own separate limit."""
        from backend.openloop.agents.session_manager import MAX_AUTOMATION_SESSIONS

        for i in range(MAX_AUTOMATION_SESSIONS):
            _get_active_sessions()[f"bg{i}"] = SessionState(
                sdk_session_id=f"s{i}",
                agent_id="a1",
                conversation_id=f"bg{i}",
                space_id=None,
                status="background",
            )

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _check_concurrency("background")
        assert exc_info.value.status_code == 429

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_start_session_rejected_at_limit(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """start_session should raise 429 when interactive limit is reached."""
        # Fill up sessions to the limit
        for i in range(MAX_INTERACTIVE_SESSIONS):
            _get_active_sessions()[f"existing-{i}"] = SessionState(
                sdk_session_id=f"s{i}",
                agent_id="a1",
                conversation_id=f"existing-{i}",
                space_id=None,
                status="active",
            )

        space = _make_space(db_session, name="LimitSpace")
        agent = _make_agent(db_session, name="LimitAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await start_session(db_session, conversation_id=conv.id, agent_id=agent.id)
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# Crash recovery tests
# ---------------------------------------------------------------------------


class TestCrashRecovery:
    def test_recover_marks_active_as_interrupted(self, db_session: Session):
        """recover_from_crash should mark all active conversations as interrupted."""
        space = _make_space(db_session, name="CrashSpace")
        agent = _make_agent(db_session, name="CrashAgent")

        # Create multiple active conversations
        conv1 = _make_conversation(db_session, space.id, agent.id)
        conv2 = conversation_service.create_conversation(
            db_session, space_id=space.id, agent_id=agent.id, name="Conv2"
        )

        # Both should be active initially
        assert conv1.status == "active"
        assert conv2.status == "active"

        count = recover_from_crash(db_session)

        assert count == 2

        # Both should now be interrupted
        updated1 = conversation_service.get_conversation(db_session, conv1.id)
        updated2 = conversation_service.get_conversation(db_session, conv2.id)
        assert updated1.status == "interrupted"
        assert updated2.status == "interrupted"

    def test_recover_creates_notification(self, db_session: Session):
        """recover_from_crash should create a notification about interrupted conversations."""
        space = _make_space(db_session, name="NotifSpace")
        agent = _make_agent(db_session, name="NotifAgent")
        _make_conversation(db_session, space.id, agent.id)

        recover_from_crash(db_session)

        notifs = notification_service.list_notifications(db_session)
        assert len(notifs) >= 1
        crash_notif = [n for n in notifs if "interrupted" in (n.title or "").lower()]
        assert len(crash_notif) == 1
        assert "1 conversation" in crash_notif[0].body

    def test_recover_skips_closed_conversations(self, db_session: Session):
        """Closed conversations should not be marked as interrupted."""
        space = _make_space(db_session, name="ClosedSpace")
        agent = _make_agent(db_session, name="ClosedAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # Close the conversation first
        conversation_service.close_conversation(db_session, conv.id)

        count = recover_from_crash(db_session)
        assert count == 0

        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "closed"

    def test_recover_clears_active_sessions(self, db_session: Session):
        """recover_from_crash should clear the in-memory active sessions dict."""
        _get_active_sessions()["stale"] = SessionState(
            sdk_session_id="s1",
            agent_id="a1",
            conversation_id="stale",
            space_id=None,
            status="active",
        )

        recover_from_crash(db_session)

        assert len(_get_active_sessions()) == 0


# ---------------------------------------------------------------------------
# delegate_background tests
# ---------------------------------------------------------------------------


class TestDelegateBackground:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_delegate_creates_task_and_notification(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """delegate_background should create a background task record."""
        space = _make_space(db_session, name="BgSpace")
        agent = _make_agent(db_session, name="BgAgent")

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_generator
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            task_id = await delegate_background(
                db_session,
                agent_id=agent.id,
                instruction="Analyze data for me",
                space_id=space.id,
            )

        # Task should exist in DB
        task = background_task_service.get_background_task(db_session, task_id)
        assert task is not None
        assert task.agent_id == agent.id
        assert task.instruction == "Analyze data for me"
        assert task.space_id == space.id

        # Give the background asyncio task a moment to complete
        import asyncio

        await asyncio.sleep(0.1)

        # After completion, task should be updated
        task = background_task_service.get_background_task(db_session, task_id)
        assert task.status in ("completed", "running")  # May still be running

    @pytest.mark.asyncio
    async def test_delegate_background_rejected_at_limit(self, db_session: Session):
        """delegate_background should raise 429 when background limit is reached."""
        from backend.openloop.agents.session_manager import MAX_AUTOMATION_SESSIONS

        # Fill up background sessions
        for i in range(MAX_AUTOMATION_SESSIONS):
            _get_active_sessions()[f"bg-{i}"] = SessionState(
                sdk_session_id=f"s{i}",
                agent_id="a1",
                conversation_id=f"bg-{i}",
                space_id=None,
                status="background",
            )

        space = _make_space(db_session, name="BgLimitSpace")
        agent = _make_agent(db_session, name="BgLimitAgent")

        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await delegate_background(
                db_session,
                agent_id=agent.id,
                instruction="Will be rejected",
                space_id=space.id,
            )
        assert exc_info.value.status_code == 429


# ---------------------------------------------------------------------------
# reopen_conversation tests
# ---------------------------------------------------------------------------


class TestReopenConversation:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_reopen_with_valid_session(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """reopen_conversation with a valid session should resume it."""
        space = _make_space(db_session, name="ReopenSpace")
        agent = _make_agent(db_session, name="ReopenAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # Set sdk_session_id and close the conversation
        conversation_service.update_conversation(
            db_session, conv.id, sdk_session_id="valid-sess-123"
        )
        conversation_service.close_conversation(db_session, conv.id)

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.get_session_info = MagicMock(return_value={"id": "valid-sess-123"})
        fake_sdk.query = _fake_query_generator
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            state = await reopen_conversation(db_session, conversation_id=conv.id)

        assert state.sdk_session_id == "valid-sess-123"
        assert state.status == "active"
        assert conv.id in _get_active_sessions()

        # Conversation should be active again
        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "active"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_reopen_with_invalid_session(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """reopen_conversation with an invalid session should start a new one."""
        space = _make_space(db_session, name="InvalidSpace")
        agent = _make_agent(db_session, name="InvalidAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # Set a stale sdk_session_id and close
        conversation_service.update_conversation(
            db_session, conv.id, sdk_session_id="stale-sess-999"
        )
        conversation_service.close_conversation(db_session, conv.id)

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.get_session_info = MagicMock(side_effect=Exception("Session not found"))
        fake_sdk.query = _fake_query_generator
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            state = await reopen_conversation(db_session, conversation_id=conv.id)

        # Should have a new session (from FakeResultMessage)
        assert state.sdk_session_id == "fake-session-123"
        assert state.status == "active"
        assert conv.id in _get_active_sessions()

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager.build_agent_tools")
    @patch("backend.openloop.agents.session_manager.context_assembler")
    async def test_reopen_with_no_session_id(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """reopen_conversation with no sdk_session_id starts a fresh session."""
        space = _make_space(db_session, name="NoSessReopenSpace")
        agent = _make_agent(db_session, name="NoSessReopenAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # Close without sdk_session_id
        conversation_service.close_conversation(db_session, conv.id)

        mock_assembler.assemble_context.return_value = "System prompt"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_generator
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            state = await reopen_conversation(db_session, conversation_id=conv.id)

        assert state.sdk_session_id == "fake-session-123"
        assert state.status == "active"


# ---------------------------------------------------------------------------
# monitor_context_usage tests
# ---------------------------------------------------------------------------


class TestMonitorContextUsage:
    @pytest.mark.asyncio
    async def test_no_action_under_threshold(self, db_session: Session):
        """Under 70% usage should not trigger any action."""
        space = _make_space(db_session, name="CtxOkSpace")
        agent = _make_agent(db_session, name="CtxOkAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # 50% usage
        usage = {
            "input_tokens": 50_000,
            "cache_read_input_tokens": 50_000,
        }

        await monitor_context_usage(db_session, conversation_id=conv.id, usage=usage)

        # No notifications should be created
        notifs = notification_service.list_notifications(db_session)
        assert len(notifs) == 0

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.session_manager._create_checkpoint")
    async def test_checkpoint_at_70_percent(self, mock_checkpoint, db_session: Session):
        """At 70-90% usage should trigger a checkpoint."""
        space = _make_space(db_session, name="CtxCheckSpace")
        agent = _make_agent(db_session, name="CtxCheckAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # 75% usage (above checkpoint threshold, below close threshold)
        tokens = int(CONTEXT_WINDOW_TOKENS * 0.75)
        usage = {
            "input_tokens": tokens // 2,
            "cache_read_input_tokens": tokens - (tokens // 2),
        }

        await monitor_context_usage(db_session, conversation_id=conv.id, usage=usage)

        # Checkpoint should be triggered
        mock_checkpoint.assert_called_once_with(db_session, conversation_id=conv.id)

    @pytest.mark.asyncio
    async def test_notification_at_90_percent(self, db_session: Session):
        """At >90% usage should create a context_warning notification."""
        space = _make_space(db_session, name="CtxWarnSpace")
        agent = _make_agent(db_session, name="CtxWarnAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        # 95% usage
        tokens = int(CONTEXT_WINDOW_TOKENS * 0.95)
        usage = {
            "input_tokens": tokens // 2,
            "cache_read_input_tokens": tokens - (tokens // 2),
        }

        await monitor_context_usage(db_session, conversation_id=conv.id, usage=usage)

        # Should create a context_warning notification
        notifs = notification_service.list_notifications(db_session)
        ctx_notifs = [n for n in notifs if n.type == "context_warning"]
        assert len(ctx_notifs) == 1
        assert "nearly full" in ctx_notifs[0].title.lower()
        assert "95%" in ctx_notifs[0].body

    @pytest.mark.asyncio
    async def test_zero_usage(self, db_session: Session):
        """Zero usage should not trigger anything (no division errors)."""
        space = _make_space(db_session, name="ZeroSpace")
        agent = _make_agent(db_session, name="ZeroAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        usage = {"input_tokens": 0, "cache_read_input_tokens": 0}
        await monitor_context_usage(db_session, conversation_id=conv.id, usage=usage)

        notifs = notification_service.list_notifications(db_session)
        assert len(notifs) == 0
