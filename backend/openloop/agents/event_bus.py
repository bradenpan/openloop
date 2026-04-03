"""In-process event bus for SSE event distribution.

Backend components (session manager, permission enforcer, notification service)
publish events here; the SSE endpoint subscribes and forwards them to clients.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

#: Safety cap on per-subscriber queue depth.  If a consumer falls this far
#: behind (or disconnects without unsubscribing), new events are dropped
#: rather than accumulating unboundedly.
_MAX_QUEUE_SIZE = 1000


class EventBus:
    """Simple in-process pub/sub for SSE events."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._global_subscribers: list[asyncio.Queue] = []

    # ------------------------------------------------------------------
    # Global (all-events) subscriptions
    # ------------------------------------------------------------------

    def subscribe_all(self) -> asyncio.Queue:
        """Subscribe to all events. Returns a queue that receives all events."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._global_subscribers.append(queue)
        return queue

    def unsubscribe_all(self, queue: asyncio.Queue) -> None:
        """Unsubscribe from all events."""
        try:
            self._global_subscribers.remove(queue)
        except ValueError:
            pass  # Already removed

    async def publish(self, event: dict) -> None:
        """Publish an event to all global subscribers."""
        for queue in self._global_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Global subscriber queue full (%d items), dropping event: %s",
                    _MAX_QUEUE_SIZE,
                    event.get("type", "unknown"),
                )

    # ------------------------------------------------------------------
    # Per-channel (e.g. per-conversation) subscriptions
    # ------------------------------------------------------------------

    def subscribe(self, channel: str) -> asyncio.Queue:
        """Subscribe to events on a specific channel (e.g. conversation_id).

        Returns a queue that receives only events published to that channel.
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE_SIZE)
        self._subscribers[channel].append(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        """Unsubscribe from a specific channel."""
        try:
            self._subscribers[channel].remove(queue)
        except (ValueError, KeyError):
            pass
        # Clean up empty channel lists
        if channel in self._subscribers and not self._subscribers[channel]:
            del self._subscribers[channel]

    async def publish_to(self, channel: str, event: dict) -> None:
        """Publish an event to channel subscribers AND all global subscribers."""
        for queue in self._subscribers.get(channel, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Channel %r subscriber queue full (%d items), dropping event: %s",
                    channel,
                    _MAX_QUEUE_SIZE,
                    event.get("type", "unknown"),
                )
        for queue in self._global_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Global subscriber queue full (%d items), dropping event: %s",
                    _MAX_QUEUE_SIZE,
                    event.get("type", "unknown"),
                )


# Singleton
event_bus = EventBus()
