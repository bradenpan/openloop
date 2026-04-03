"""Tests for the Agent Runner module.

Mocks claude_agent_sdk.query to avoid real SDK calls. Tests cover:
- run_interactive storing messages and streaming events
- close_conversation generating summary and closing conversation
- Model name mapping
- Error handling (ProcessError on resume, ExceptionGroup)
- Background delegation
- Crash recovery
- Context usage monitoring
"""

from __future__ import annotations

import types
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.agent_runner import (
    CONTEXT_WINDOW_TOKENS,
    MAX_INTERACTIVE_SESSIONS,
    MODEL_MAP,
    close_conversation,
    delegate_background,
    list_running,
    monitor_context_usage,
    recover_from_crash,
    resolve_model,
    run_interactive,
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
def _mock_permission_hooks():
    """Mock _build_hooks_dict so tests don't need the real SDK hook types.

    Permission hook logic is tested separately in test_permission_enforcer.py.
    """
    with patch(
        "backend.openloop.agents.agent_runner._build_hooks_dict",
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
# run_interactive tests
# ---------------------------------------------------------------------------


class TestRunInteractive:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    async def test_run_interactive_with_active_session(self, mock_build_tools, db_session: Session):
        """run_interactive should yield events and store messages in DB."""
        space = _make_space(db_session, name="Msg Space")
        agent = _make_agent(db_session, name="MsgAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        # Set sdk_session_id to simulate an existing session
        conversation_service.update_conversation(
            db_session, conv.id, sdk_session_id="sess-msg-123"
        )

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_generator_with_stream
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = FakeStreamEvent

        # Pre-save user message (the API route does this, not run_interactive)
        conversation_service.add_message(
            db_session, conversation_id=conv.id, role="user", content="Hello agent"
        )

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            events = []
            async for evt in run_interactive(
                db_session, conversation_id=conv.id, message="Hello agent"
            ):
                events.append(evt)

        # Should have stream events + no error
        stream_events = [e for e in events if e.get("type") == "stream"]
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(stream_events) == 2
        assert len(error_events) == 0

        # User message was pre-saved by caller; assistant message saved by run_interactive
        messages = conversation_service.get_messages(db_session, conv.id)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[0].content == "Hello agent"
        assert messages[1].role == "assistant"
        assert messages[1].content == "Hello world"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
    async def test_run_interactive_first_message(
        self, mock_assembler, mock_build_tools, db_session: Session
    ):
        """run_interactive with no sdk_session_id should assemble context and start fresh."""
        space = _make_space(db_session, name="First Msg Space")
        agent = _make_agent(db_session, name="FirstMsgAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_assembler.assemble_context.return_value = "System prompt here"
        mock_build_tools.return_value = MagicMock()

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_generator_with_stream
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = FakeStreamEvent

        # No sdk_session_id set — this is the first message
        conversation_service.add_message(
            db_session, conversation_id=conv.id, role="user", content="Hello"
        )

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            events = []
            async for evt in run_interactive(
                db_session, conversation_id=conv.id, message="Hello"
            ):
                events.append(evt)

        # Context assembler should have been called for first message
        mock_assembler.assemble_context.assert_called_once_with(
            db_session,
            agent_id=agent.id,
            space_id=space.id,
            conversation_id=conv.id,
        )

        # sdk_session_id should be persisted from the result
        updated_conv = conversation_service.get_conversation(db_session, conv.id)
        assert updated_conv.sdk_session_id == "fake-session-123"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    async def test_run_interactive_sdk_error_marks_interrupted(
        self, mock_build_tools, db_session: Session
    ):
        """SDK errors during run_interactive should mark conversation as interrupted."""
        space = _make_space(db_session, name="SdkErr Space")
        agent = _make_agent(db_session, name="SdkErrAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        # Set sdk_session_id to simulate existing session
        conversation_service.update_conversation(
            db_session, conv.id, sdk_session_id="sess-err-789"
        )

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_raises
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage
        fake_sdk.StreamEvent = FakeStreamEvent

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            events = []
            async for evt in run_interactive(
                db_session, conversation_id=conv.id, message="Will fail"
            ):
                events.append(evt)

        # Should yield an error event
        assert any(e.get("type") == "error" for e in events)

        # Conversation should be interrupted
        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "interrupted"


# ---------------------------------------------------------------------------
# close_conversation tests
# ---------------------------------------------------------------------------


class TestCloseConversation:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    async def test_close_conversation_generates_summary(self, mock_build_tools, db_session: Session):
        """close_conversation should generate a summary, store it, and close the conv."""
        space = _make_space(db_session, name="Close Space")
        agent = _make_agent(db_session, name="CloseAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        # Set sdk_session_id so close_conversation can generate a summary
        conversation_service.update_conversation(
            db_session, conv.id, sdk_session_id="sess-close-001"
        )

        async def _summary_query(*args, **kwargs):
            yield FakeResultMessage(result="Summary: discussed X, decided Y.")

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _summary_query
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with (
            patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}),
            patch(
                "backend.openloop.agents.agent_runner._new_db_session",
                return_value=db_session,
            ),
        ):
            summary = await close_conversation(db_session, conversation_id=conv.id)

        assert summary == "Summary: discussed X, decided Y."

        # Conversation should be closed
        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "closed"

        # Summary should be stored
        summaries = conversation_service.get_summaries(db_session, conversation_id=conv.id)
        assert len(summaries) == 1
        assert "discussed X" in summaries[0].summary

    @pytest.mark.asyncio
    async def test_close_conversation_no_sdk_session_still_closes(self, db_session: Session):
        """If there's no SDK session, close_conversation should still close the conv."""
        space = _make_space(db_session, name="NoSdk Space")
        agent = _make_agent(db_session, name="NoSdkAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        summary = await close_conversation(db_session, conversation_id=conv.id)

        assert summary == ""

        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "closed"

    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    async def test_close_conversation_sdk_error_still_closes(
        self, mock_build_tools, db_session: Session
    ):
        """If SDK summary generation fails, should still close with fallback text."""
        space = _make_space(db_session, name="FailClose Space")
        agent = _make_agent(db_session, name="FailCloseAgent")
        conv = _make_conversation(db_session, space.id, agent.id)

        mock_build_tools.return_value = MagicMock()

        # Set sdk_session_id
        conversation_service.update_conversation(
            db_session, conv.id, sdk_session_id="sess-fail-close"
        )

        fake_sdk = types.ModuleType("claude_agent_sdk")
        fake_sdk.query = _fake_query_raises
        fake_sdk.ClaudeAgentOptions = MagicMock()
        fake_sdk.ResultMessage = FakeResultMessage

        with patch.dict("sys.modules", {"claude_agent_sdk": fake_sdk}):
            summary = await close_conversation(db_session, conversation_id=conv.id)

        assert "Summary generation failed" in summary

        # Conversation should still be closed
        updated = conversation_service.get_conversation(db_session, conv.id)
        assert updated.status == "closed"


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

    def test_recover_marks_orphaned_background_tasks_as_failed(self, db_session: Session):
        """recover_from_crash should mark RUNNING/QUEUED background tasks as FAILED."""
        from contract.enums import BackgroundTaskStatus
        from backend.openloop.db.models import BackgroundTask

        agent = _make_agent(db_session, name="TaskAgent")

        running_task = BackgroundTask(
            agent_id=agent.id,
            instruction="running task",
            status=BackgroundTaskStatus.RUNNING,
        )
        queued_task = BackgroundTask(
            agent_id=agent.id,
            instruction="queued task",
            status=BackgroundTaskStatus.QUEUED,
        )
        completed_task = BackgroundTask(
            agent_id=agent.id,
            instruction="completed task",
            status=BackgroundTaskStatus.COMPLETED,
        )
        db_session.add_all([running_task, queued_task, completed_task])
        db_session.commit()

        recover_from_crash(db_session)

        db_session.expire_all()
        r = db_session.query(BackgroundTask).filter(BackgroundTask.id == running_task.id).first()
        q = db_session.query(BackgroundTask).filter(BackgroundTask.id == queued_task.id).first()
        c = db_session.query(BackgroundTask).filter(BackgroundTask.id == completed_task.id).first()

        assert r.status == BackgroundTaskStatus.FAILED
        assert "restart" in r.error.lower()
        assert r.completed_at is not None

        assert q.status == BackgroundTaskStatus.FAILED
        assert "restart" in q.error.lower()
        assert q.completed_at is not None

        # Completed task should not be touched
        assert c.status == BackgroundTaskStatus.COMPLETED
        assert c.error is None


# ---------------------------------------------------------------------------
# delegate_background tests
# ---------------------------------------------------------------------------


class TestDelegateBackground:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.agent_runner.build_agent_tools")
    @patch("backend.openloop.agents.agent_runner.context_assembler")
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
    @patch("backend.openloop.agents.agent_runner._create_checkpoint")
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
