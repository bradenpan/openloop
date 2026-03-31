"""Odin API routes — system-level AI front door."""

import asyncio
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.openloop.agents.event_bus import event_bus
from backend.openloop.agents.odin_service import odin
from backend.openloop.api.schemas import MessageResponse, OdinMessageRequest
from backend.openloop.database import get_db
from backend.openloop.services import conversation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/odin", tags=["odin"])


@router.post("/message", response_model=MessageResponse, status_code=201)
async def send_odin_message(
    body: OdinMessageRequest,
    db: Session = Depends(get_db),
) -> MessageResponse:
    """Send a message to Odin. Returns the stored user message (201).

    The Odin response streams via SSE through the event bus.
    """
    # Ensure agent and conversation exist
    conversation_id = await odin.ensure_conversation(db)

    # Store the user message in DB
    user_msg = conversation_service.add_message(
        db,
        conversation_id=conversation_id,
        role="user",
        content=body.content,
    )

    # Kick off Odin processing in the background so we can return 201 immediately.
    # The background task creates its own DB session because the request-scoped
    # session will be closed when this request finishes.
    async def _process_odin_response() -> None:
        from backend.openloop.database import SessionLocal

        bg_db = SessionLocal()
        try:
            async for event in odin.send_message(bg_db, body.content):
                await event_bus.publish(event)
        except Exception:
            logger.exception("Error processing Odin response")
        finally:
            bg_db.close()

    asyncio.create_task(_process_odin_response())

    return MessageResponse.model_validate(user_msg)
