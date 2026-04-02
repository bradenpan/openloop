"""SSE streaming endpoint — multiplexed event stream for all frontend consumers."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from collections.abc import AsyncGenerator
from dataclasses import dataclass

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.openloop.agents.event_bus import event_bus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["events"])

KEEPALIVE_INTERVAL_SECONDS = 30
REPLAY_BUFFER_MAX = 100


# ---------------------------------------------------------------------------
# Replay buffer — stores recent SSE frames for reconnecting clients
# ---------------------------------------------------------------------------


@dataclass
class _SSEFrame:
    """A single SSE frame stored for replay."""

    event_id: int
    frame: str


class _ReplayBuffer:
    """Thread-safe ring buffer of recent SSE frames."""

    def __init__(self, maxlen: int = REPLAY_BUFFER_MAX) -> None:
        self._buf: deque[_SSEFrame] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._counter = 0

    def push(self, event: dict) -> tuple[int, str]:
        """Store an event and return (event_id, sse_frame_str)."""
        with self._lock:
            self._counter += 1
            eid = self._counter
            event_type = event.get("type", "message")
            data = json.dumps(event)
            frame = f"id: {eid}\nevent: {event_type}\ndata: {data}\n\n"
            self._buf.append(_SSEFrame(event_id=eid, frame=frame))
            return eid, frame

    def replay_after(self, last_id: int) -> list[str]:
        """Return all frames with event_id > last_id, in order."""
        with self._lock:
            return [f.frame for f in self._buf if f.event_id > last_id]

    @property
    def current_id(self) -> int:
        with self._lock:
            return self._counter


_replay_buffer = _ReplayBuffer()


async def _event_stream(last_event_id: int = 0) -> AsyncGenerator[str, None]:
    """Generate SSE-formatted events from the event bus.

    Yields standard SSE format:
        id: <counter>
        event: <type>
        data: <json>

    If last_event_id > 0, replays missed events from the buffer first.
    Sends a keepalive comment every 30 seconds to prevent connection timeout.
    """
    # Replay missed events for reconnecting clients
    if last_event_id > 0:
        missed = _replay_buffer.replay_after(last_event_id)
        for frame in missed:
            yield frame

    queue = event_bus.subscribe_all()
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

            _eid, frame = _replay_buffer.push(event)
            yield frame
    except asyncio.CancelledError:
        logger.debug("SSE client disconnected")
    finally:
        event_bus.unsubscribe_all(queue)


@router.get("/events")
async def sse_events(request: Request) -> StreamingResponse:
    """Multiplexed SSE endpoint — streams all events to the frontend.

    Supports reconnection via the Last-Event-ID header: on reconnect the
    client receives any events it missed from the in-memory replay buffer.
    """
    last_event_id = 0
    raw = request.headers.get("last-event-id", "")
    if raw:
        try:
            last_event_id = int(raw)
        except ValueError:
            pass

    return StreamingResponse(
        _event_stream(last_event_id=last_event_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
