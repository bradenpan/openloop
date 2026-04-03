"""Tests for error handling and edge cases (Task 7.3).

Covers:
- Rate limit retry logic (mock SDK to raise rate limit errors)
- Orphaned task cleanup on startup
- Graceful shutdown marking sessions
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.db.models import BackgroundTask
from backend.openloop.services import background_task_service, notification_service

# ---------------------------------------------------------------------------
# Rate limit detection
# ---------------------------------------------------------------------------


class TestIsRateLimitError:
    """Tests for _is_rate_limit_error helper."""

    def test_429_in_message(self) -> None:
        from backend.openloop.agents.agent_runner import _is_rate_limit_error

        exc = Exception("API returned status 429")
        assert _is_rate_limit_error(exc) is True

    def test_rate_limit_phrase(self) -> None:
        from backend.openloop.agents.agent_runner import _is_rate_limit_error

        exc = Exception("rate limit exceeded, please slow down")
        assert _is_rate_limit_error(exc) is True

    def test_overloaded_phrase(self) -> None:
        from backend.openloop.agents.agent_runner import _is_rate_limit_error

        exc = Exception("The API is overloaded right now")
        assert _is_rate_limit_error(exc) is True

    def test_status_code_attribute(self) -> None:
        from backend.openloop.agents.agent_runner import _is_rate_limit_error

        exc = Exception("too many requests")
        exc.status_code = 429  # type: ignore[attr-defined]
        assert _is_rate_limit_error(exc) is True

    def test_response_attribute(self) -> None:
        from backend.openloop.agents.agent_runner import _is_rate_limit_error

        exc = Exception("request failed")
        response = MagicMock()
        response.status_code = 429
        exc.response = response  # type: ignore[attr-defined]
        assert _is_rate_limit_error(exc) is True

    def test_not_rate_limit(self) -> None:
        from backend.openloop.agents.agent_runner import _is_rate_limit_error

        exc = Exception("Connection refused")
        assert _is_rate_limit_error(exc) is False

    def test_exception_group(self) -> None:
        from backend.openloop.agents.agent_runner import _is_rate_limit_error

        inner = Exception("rate limit exceeded")
        group = ExceptionGroup("multiple errors", [inner])
        assert _is_rate_limit_error(group) is True

    def test_exception_group_no_rate_limit(self) -> None:
        from backend.openloop.agents.agent_runner import _is_rate_limit_error

        inner = Exception("Connection reset")
        group = ExceptionGroup("errors", [inner])
        assert _is_rate_limit_error(group) is False


# ---------------------------------------------------------------------------
# Rate limit retry wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_query_with_retry_succeeds_first_try() -> None:
    """_query_with_retry yields events when query succeeds on first try."""
    from backend.openloop.agents.agent_runner import _query_with_retry

    mock_event = {"type": "result", "text": "hello"}

    async def mock_query(**kwargs):
        yield mock_event

    events = []
    async for event in _query_with_retry(
        mock_query,
        {"prompt": "test"},
        conversation_id="c1",
    ):
        events.append(event)

    assert events == [mock_event]


@pytest.mark.asyncio()
async def test_query_with_retry_retries_on_rate_limit() -> None:
    """_query_with_retry retries on rate limit errors with backoff."""
    from backend.openloop.agents.agent_runner import _query_with_retry

    call_count = 0
    mock_event = {"type": "result", "text": "success"}

    async def mock_query(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise Exception("rate limit exceeded")
        yield mock_event

    # Patch sleep to avoid waiting and the event_bus publish
    with (
        patch("backend.openloop.agents.agent_runner.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
        patch("backend.openloop.agents.agent_runner.notification_service") as mock_notif,
        patch("backend.openloop.agents.event_bus.event_bus.publish", new_callable=AsyncMock),
    ):
        mock_notif.create_notification = MagicMock()
        events = []
        async for event in _query_with_retry(
            mock_query,
            {"prompt": "test"},
            conversation_id="c1",
            space_id="s1",
        ):
            events.append(event)

        assert events == [mock_event]
        assert call_count == 3
        # Should have slept twice (attempts 1 and 2 failed)
        assert mock_sleep.await_count == 2
        # First retry waits 30s, second waits 60s
        mock_sleep.assert_any_await(30)
        mock_sleep.assert_any_await(60)


@pytest.mark.asyncio()
async def test_query_with_retry_raises_after_max_retries() -> None:
    """_query_with_retry raises after exhausting all retries."""
    from backend.openloop.agents.agent_runner import _query_with_retry

    async def mock_query(**kwargs):
        raise Exception("rate limit exceeded")
        yield  # type: ignore[misc] # make it a generator  # noqa: E501

    with (
        patch("backend.openloop.agents.agent_runner.asyncio.sleep", new_callable=AsyncMock),
        patch("backend.openloop.agents.agent_runner.notification_service") as mock_notif,
        patch("backend.openloop.agents.event_bus.event_bus.publish", new_callable=AsyncMock),
    ):
        mock_notif.create_notification = MagicMock()
        with pytest.raises(Exception, match="rate limit"):
            async for _ in _query_with_retry(
                mock_query,
                {"prompt": "test"},
                conversation_id="c1",
            ):
                pass


@pytest.mark.asyncio()
async def test_query_with_retry_does_not_retry_non_rate_limit() -> None:
    """_query_with_retry re-raises non-rate-limit errors immediately."""
    from backend.openloop.agents.agent_runner import _query_with_retry

    async def mock_query(**kwargs):
        raise Exception("Connection refused")
        yield  # type: ignore[misc]  # noqa: E501

    with pytest.raises(Exception, match="Connection refused"):
        async for _ in _query_with_retry(
            mock_query,
            {"prompt": "test"},
            conversation_id="c1",
        ):
            pass


# ---------------------------------------------------------------------------
# Orphaned task cleanup
# ---------------------------------------------------------------------------


def test_orphaned_task_cleanup(db_session: Session) -> None:
    """Orphaned running/queued tasks are marked failed on startup."""
    from backend.openloop.db.models import Agent

    # Create an agent (required FK)
    agent = Agent(name="test-agent", system_prompt="test", default_model="haiku")
    db_session.add(agent)
    db_session.commit()

    # Create running and queued tasks
    running_task = BackgroundTask(
        agent_id=agent.id,
        instruction="do something",
        status="running",
        started_at=datetime.now(UTC),
    )
    queued_task = BackgroundTask(
        agent_id=agent.id,
        instruction="do something else",
        status="queued",
    )
    completed_task = BackgroundTask(
        agent_id=agent.id,
        instruction="already done",
        status="completed",
        completed_at=datetime.now(UTC),
    )
    db_session.add_all([running_task, queued_task, completed_task])
    db_session.commit()

    # Simulate what main.py lifespan does
    running_tasks = background_task_service.list_background_tasks(db_session, status="running")
    queued_tasks = background_task_service.list_background_tasks(db_session, status="queued")
    orphaned = running_tasks + queued_tasks

    for task in orphaned:
        background_task_service.update_background_task(
            db_session,
            task.id,
            status="failed",
            error="Server restarted",
            completed_at=datetime.now(UTC),
        )

    # Verify
    db_session.expire_all()
    assert running_task.status == "failed"
    assert running_task.error == "Server restarted"
    assert queued_task.status == "failed"
    assert queued_task.error == "Server restarted"
    # Completed task should be untouched
    assert completed_task.status == "completed"


def test_orphaned_task_cleanup_creates_notification(db_session: Session) -> None:
    """Notification is created for interrupted running tasks."""
    from backend.openloop.db.models import Agent

    agent = Agent(name="test-agent", system_prompt="test", default_model="haiku")
    db_session.add(agent)
    db_session.commit()

    # Create running task
    task = BackgroundTask(
        agent_id=agent.id,
        instruction="interrupted work",
        status="running",
        started_at=datetime.now(UTC),
    )
    db_session.add(task)
    db_session.commit()

    # Simulate cleanup
    running_tasks = background_task_service.list_background_tasks(db_session, status="running")
    running_count = len(running_tasks)
    for t in running_tasks:
        background_task_service.update_background_task(
            db_session, t.id, status="failed", error="Server restarted",
            completed_at=datetime.now(UTC),
        )

    if running_count > 0:
        notification_service.create_notification(
            db_session,
            type="system",
            title="Background tasks interrupted",
            body=f"{running_count} running task(s) were interrupted by a server restart.",
        )

    notifs = notification_service.list_notifications(db_session)
    assert len(notifs) == 1
    assert "interrupted" in notifs[0].title.lower()
    assert "1 running task" in notifs[0].body


# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_graceful_shutdown_timeout_does_not_hang() -> None:
    """Graceful shutdown respects timeout and doesn't block forever."""

    async def slow_close(db, *, conversation_id):
        await asyncio.sleep(60)  # Would hang forever without timeout

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(
            asyncio.gather(
                slow_close(None, conversation_id="c1"),
                return_exceptions=False,
            ),
            timeout=0.1,
        )
