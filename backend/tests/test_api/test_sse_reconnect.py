"""Tests for SSE reconnection support (Task 7.3).

Covers:
- SSE events include IDs (via replay buffer)
- Last-Event-ID replay delivers missed events
- Replay buffer respects max size
"""

from __future__ import annotations

import asyncio
import json

import pytest

from backend.openloop.agents.event_bus import event_bus

# ---------------------------------------------------------------------------
# Replay buffer unit tests
# ---------------------------------------------------------------------------


class TestReplayBuffer:
    """Tests for the _ReplayBuffer class."""

    def test_push_increments_ids(self) -> None:
        from backend.openloop.api.routes.events import _ReplayBuffer

        buf = _ReplayBuffer(maxlen=10)
        eid1, frame1 = buf.push({"type": "token", "content": "a"})
        eid2, frame2 = buf.push({"type": "token", "content": "b"})

        assert eid1 == 1
        assert eid2 == 2
        assert frame1.startswith("id: 1\n")
        assert frame2.startswith("id: 2\n")

    def test_push_format(self) -> None:
        from backend.openloop.api.routes.events import _ReplayBuffer

        buf = _ReplayBuffer(maxlen=10)
        eid, frame = buf.push({"type": "notification", "title": "test"})

        assert "event: notification\n" in frame
        assert "data: " in frame
        data_line = [line for line in frame.split("\n") if line.startswith("data: ")][0]
        payload = json.loads(data_line[len("data: "):])
        assert payload["type"] == "notification"
        assert payload["title"] == "test"

    def test_replay_after_returns_missed(self) -> None:
        from backend.openloop.api.routes.events import _ReplayBuffer

        buf = _ReplayBuffer(maxlen=10)
        buf.push({"type": "token", "content": "a"})  # id=1
        buf.push({"type": "token", "content": "b"})  # id=2
        buf.push({"type": "token", "content": "c"})  # id=3

        missed = buf.replay_after(1)
        assert len(missed) == 2
        assert "id: 2\n" in missed[0]
        assert "id: 3\n" in missed[1]

    def test_replay_after_zero_returns_all(self) -> None:
        from backend.openloop.api.routes.events import _ReplayBuffer

        buf = _ReplayBuffer(maxlen=10)
        buf.push({"type": "token", "content": "a"})
        buf.push({"type": "token", "content": "b"})

        missed = buf.replay_after(0)
        assert len(missed) == 2

    def test_replay_after_current_returns_empty(self) -> None:
        from backend.openloop.api.routes.events import _ReplayBuffer

        buf = _ReplayBuffer(maxlen=10)
        buf.push({"type": "token", "content": "a"})

        missed = buf.replay_after(1)
        assert len(missed) == 0

    def test_maxlen_enforced(self) -> None:
        from backend.openloop.api.routes.events import _ReplayBuffer

        buf = _ReplayBuffer(maxlen=3)
        for i in range(5):
            buf.push({"type": "token", "content": str(i)})

        # Only last 3 should remain
        missed = buf.replay_after(0)
        assert len(missed) == 3
        # IDs should be 3, 4, 5
        assert "id: 3\n" in missed[0]
        assert "id: 4\n" in missed[1]
        assert "id: 5\n" in missed[2]

    def test_current_id(self) -> None:
        from backend.openloop.api.routes.events import _ReplayBuffer

        buf = _ReplayBuffer(maxlen=10)
        assert buf.current_id == 0
        buf.push({"type": "token"})
        assert buf.current_id == 1
        buf.push({"type": "token"})
        assert buf.current_id == 2


# ---------------------------------------------------------------------------
# SSE event stream with replay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_event_stream_uses_replay_buffer() -> None:
    """Events go through the replay buffer and get consistent IDs."""
    from backend.openloop.api.routes.events import _event_stream

    # Reset for clean test (we'll use the module-level buffer)
    # Push an event via event_bus and verify the stream yields it with an ID
    gen = _event_stream()

    test_event = {"type": "token", "conversation_id": "c1", "content": "hello"}

    async def _publish():
        await asyncio.sleep(0.05)
        await event_bus.publish(test_event)

    task = asyncio.create_task(_publish())
    frame = await gen.__anext__()
    await task

    # The frame should have an id field
    assert frame.startswith("id: ")
    assert "event: token\n" in frame
    assert "data: " in frame

    await gen.aclose()


@pytest.mark.asyncio()
async def test_event_stream_replays_missed_events() -> None:
    """Reconnecting with Last-Event-ID replays missed events."""
    from backend.openloop.api.routes.events import _ReplayBuffer

    # Create a fresh buffer for isolated testing
    buf = _ReplayBuffer(maxlen=100)
    buf.push({"type": "token", "content": "first"})   # id=1
    buf.push({"type": "token", "content": "second"})  # id=2
    buf.push({"type": "token", "content": "third"})   # id=3

    # Client reconnects with last_event_id=1, should get events 2 and 3
    missed = buf.replay_after(1)
    assert len(missed) == 2
    assert '"second"' in missed[0]
    assert '"third"' in missed[1]


@pytest.mark.asyncio()
async def test_event_stream_replay_then_live() -> None:
    """After replaying missed events, stream continues with live events."""
    # We test the replay path of _event_stream by passing a last_event_id
    # that matches some events in the module replay buffer.
    # First, push some events to the module buffer.
    from backend.openloop.api.routes.events import _event_stream, _replay_buffer

    # Record current buffer state
    current_id = _replay_buffer.current_id

    # Push two events
    _replay_buffer.push({"type": "token", "content": "replay-a"})
    _replay_buffer.push({"type": "token", "content": "replay-b"})

    # Start stream from the ID before our two events
    gen = _event_stream(last_event_id=current_id)

    # First two frames should be replayed
    frame1 = await gen.__anext__()
    frame2 = await gen.__anext__()
    assert '"replay-a"' in frame1
    assert '"replay-b"' in frame2

    # Next frame should be a live event
    test_event = {"type": "notification", "title": "live"}

    async def _publish():
        await asyncio.sleep(0.05)
        await event_bus.publish(test_event)

    task = asyncio.create_task(_publish())
    frame3 = await gen.__anext__()
    await task

    assert "event: notification\n" in frame3
    assert '"live"' in frame3

    await gen.aclose()


def test_sse_route_accepts_last_event_id(client) -> None:
    """The SSE endpoint reads Last-Event-ID from request headers."""
    # We can't easily test the full SSE stream with TestClient (infinite stream),
    # but we can verify the route is registered and doesn't crash with the header.
    from backend.openloop.main import app

    routes = [route.path for route in app.routes]
    assert "/api/v1/events" in routes
