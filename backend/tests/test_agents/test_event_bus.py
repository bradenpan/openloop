"""Tests for the in-process event bus."""

import pytest

from backend.openloop.agents.event_bus import EventBus


@pytest.fixture()
def bus() -> EventBus:
    """Fresh event bus per test (don't use singleton to avoid cross-test leaks)."""
    return EventBus()


@pytest.mark.asyncio()
async def test_publish_subscribe_single(bus: EventBus) -> None:
    """A single subscriber receives published events."""
    queue = bus.subscribe_all()

    event = {"type": "token", "conversation_id": "c1", "content": "hello"}
    await bus.publish(event)

    received = queue.get_nowait()
    assert received == event


@pytest.mark.asyncio()
async def test_publish_subscribe_multiple(bus: EventBus) -> None:
    """Multiple subscribers each receive all published events."""
    q1 = bus.subscribe_all()
    q2 = bus.subscribe_all()

    event = {"type": "token", "conversation_id": "c1", "content": "world"}
    await bus.publish(event)

    assert q1.get_nowait() == event
    assert q2.get_nowait() == event


@pytest.mark.asyncio()
async def test_unsubscribe_cleanup(bus: EventBus) -> None:
    """After unsubscribing, the queue no longer receives events."""
    queue = bus.subscribe_all()
    bus.unsubscribe_all(queue)

    await bus.publish({"type": "token", "conversation_id": "c1", "content": "nope"})

    assert queue.empty()


@pytest.mark.asyncio()
async def test_unsubscribe_idempotent(bus: EventBus) -> None:
    """Unsubscribing a queue that's already removed does not raise."""
    queue = bus.subscribe_all()
    bus.unsubscribe_all(queue)
    # Should not raise
    bus.unsubscribe_all(queue)


@pytest.mark.asyncio()
async def test_multiple_events_ordering(bus: EventBus) -> None:
    """Events are received in publish order."""
    queue = bus.subscribe_all()

    events = [
        {"type": "token", "content": "a"},
        {"type": "token", "content": "b"},
        {"type": "token", "content": "c"},
    ]
    for e in events:
        await bus.publish(e)

    received = []
    while not queue.empty():
        received.append(queue.get_nowait())

    assert received == events


@pytest.mark.asyncio()
async def test_no_subscribers_publish_succeeds(bus: EventBus) -> None:
    """Publishing with no subscribers does not raise."""
    await bus.publish({"type": "token", "content": "orphan"})
