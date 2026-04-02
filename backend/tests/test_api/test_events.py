"""Tests for the SSE streaming endpoint.

Tests the _event_stream async generator directly rather than via HTTP,
because infinite SSE streams and synchronous TestClient don't mix well.
The generator tests cover all the meaningful behavior.
"""

import asyncio
import json

import pytest

from backend.openloop.agents.event_bus import event_bus


@pytest.mark.asyncio()
async def test_event_stream_format() -> None:
    """_event_stream yields correctly formatted SSE frames."""
    from backend.openloop.api.routes.events import _event_stream

    test_event = {"type": "token", "conversation_id": "c1", "content": "hello"}

    gen = _event_stream()

    async def _publish():
        await asyncio.sleep(0.05)
        await event_bus.publish(test_event)

    task = asyncio.create_task(_publish())
    frame = await gen.__anext__()
    await task

    # Verify SSE format: id, event, data lines
    assert frame.startswith("id: ")
    assert "event: token\n" in frame
    assert "data: " in frame

    # Parse the data payload
    data_line = [line for line in frame.split("\n") if line.startswith("data: ")][0]
    payload = json.loads(data_line[len("data: ") :])
    assert payload == test_event

    await gen.aclose()


@pytest.mark.asyncio()
async def test_event_stream_keepalive() -> None:
    """_event_stream sends keepalive when no events arrive within timeout."""
    import backend.openloop.api.routes.events as events_module
    from backend.openloop.api.routes.events import _event_stream

    original = events_module.KEEPALIVE_INTERVAL_SECONDS
    events_module.KEEPALIVE_INTERVAL_SECONDS = 0.1  # type: ignore[assignment]
    try:
        gen = _event_stream()
        frame = await gen.__anext__()
        assert frame == ": keepalive\n\n"
        await gen.aclose()
    finally:
        events_module.KEEPALIVE_INTERVAL_SECONDS = original  # type: ignore[assignment]


@pytest.mark.asyncio()
async def test_event_stream_increments_id() -> None:
    """Event IDs increment with each event."""
    from backend.openloop.api.routes.events import _event_stream

    gen = _event_stream()

    async def _publish_two():
        await asyncio.sleep(0.05)
        await event_bus.publish({"type": "token", "content": "a"})
        await event_bus.publish({"type": "token", "content": "b"})

    task = asyncio.create_task(_publish_two())

    frame1 = await gen.__anext__()
    frame2 = await gen.__anext__()
    await task

    # Extract IDs and verify they increment
    id1 = int(frame1.split("\n")[0].split(": ")[1])
    id2 = int(frame2.split("\n")[0].split(": ")[1])
    assert id2 == id1 + 1

    await gen.aclose()


@pytest.mark.asyncio()
async def test_event_stream_unsubscribes_on_close() -> None:
    """Closing the generator unsubscribes from the event bus."""
    from backend.openloop.api.routes.events import _event_stream

    initial_count = len(event_bus._global_subscribers)

    gen = _event_stream()

    # The generator hasn't started yet — we need to advance it to subscribe.
    # Trigger a keepalive by using a short timeout.
    import backend.openloop.api.routes.events as events_module

    original = events_module.KEEPALIVE_INTERVAL_SECONDS
    events_module.KEEPALIVE_INTERVAL_SECONDS = 0.05  # type: ignore[assignment]
    try:
        await gen.__anext__()  # triggers subscribe + first keepalive
        assert len(event_bus._global_subscribers) == initial_count + 1

        await gen.aclose()
        assert len(event_bus._global_subscribers) == initial_count
    finally:
        events_module.KEEPALIVE_INTERVAL_SECONDS = original  # type: ignore[assignment]


@pytest.mark.asyncio()
async def test_event_stream_event_type_field() -> None:
    """The SSE 'event' field matches the event's type value."""
    from backend.openloop.api.routes.events import _event_stream

    gen = _event_stream()

    async def _publish():
        await asyncio.sleep(0.05)
        await event_bus.publish({"type": "error", "message": "oops"})

    task = asyncio.create_task(_publish())
    frame = await gen.__anext__()
    await task

    assert "event: error\n" in frame

    await gen.aclose()


def test_sse_route_registered() -> None:
    """The /api/v1/events route is registered on the FastAPI app."""
    from backend.openloop.main import app

    routes = [route.path for route in app.routes]
    assert "/api/v1/events" in routes
