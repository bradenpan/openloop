"""SSE streaming endpoint — multiplexed event stream for all frontend consumers."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.openloop.agents.event_bus import event_bus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["events"])

KEEPALIVE_INTERVAL_SECONDS = 30


async def _event_stream() -> AsyncGenerator[str, None]:
    """Generate SSE-formatted events from the event bus.

    Yields standard SSE format:
        id: <counter>
        event: <type>
        data: <json>

    Sends a keepalive comment every 30 seconds to prevent connection timeout.
    """
    queue = event_bus.subscribe_all()
    event_id = 0
    try:
        while True:
            try:
                event: dict = await asyncio.wait_for(
                    queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS
                )
            except TimeoutError:
                # Send keepalive comment to prevent connection timeout
                yield ": keepalive\n\n"
                continue

            event_id += 1
            event_type = event.get("type", "message")
            data = json.dumps(event)
            yield f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"
    except asyncio.CancelledError:
        logger.debug("SSE client disconnected")
    finally:
        event_bus.unsubscribe_all(queue)


@router.get("/events")
async def sse_events() -> StreamingResponse:
    """Multiplexed SSE endpoint — streams all events to the frontend."""
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
