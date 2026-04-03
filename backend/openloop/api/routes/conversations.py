import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.openloop.agents.event_bus import event_bus
from contract.enums import ConversationStatus

from backend.openloop.api.schemas import (
    ConversationCreate,
    ConversationResponse,
    MessageCreate,
    MessageResponse,
    SteerRequest,
    SteerResponse,
    SummaryResponse,
)
from backend.openloop.database import get_db
from backend.openloop.services import conversation_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponse, status_code=201)
def create_conversation(
    body: ConversationCreate, db: Session = Depends(get_db)
) -> ConversationResponse:
    conv = conversation_service.create_conversation(
        db,
        agent_id=body.agent_id,
        name=body.name,
        space_id=body.space_id,
        model_override=body.model_override,
    )
    return ConversationResponse.model_validate(conv)


@router.get("", response_model=list[ConversationResponse])
def list_conversations(
    space_id: str | None = Query(None),
    status: ConversationStatus | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[ConversationResponse]:
    convs = conversation_service.list_conversations(
        db, space_id=space_id, status=status, limit=limit, offset=offset
    )
    return [ConversationResponse.model_validate(c) for c in convs]


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(conversation_id: str, db: Session = Depends(get_db)) -> ConversationResponse:
    conv = conversation_service.get_conversation(db, conversation_id)
    return ConversationResponse.model_validate(conv)


async def _stream_agent_response(conversation_id: str, message: str) -> None:
    """Background task: send message to agent runner and publish events to event bus.

    Creates its own DB session because this runs after the request-scoped session is closed.
    """
    from backend.openloop.agents import agent_runner
    from backend.openloop.database import SessionLocal

    db = SessionLocal()
    try:
        async for event in agent_runner.run_interactive(
            db, conversation_id=conversation_id, message=message
        ):
            await event_bus.publish(event)
    except (Exception, ExceptionGroup):
        logger.exception("Background agent streaming failed for conversation %s", conversation_id)
        await event_bus.publish(
            {
                "type": "error",
                "conversation_id": conversation_id,
                "message": "Agent response streaming failed unexpectedly.",
            }
        )
    finally:
        db.close()


@router.post("/{conversation_id}/messages", response_model=MessageResponse, status_code=201)
async def send_message(
    conversation_id: str,
    body: MessageCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> MessageResponse:
    msg = conversation_service.add_message(
        db, conversation_id=conversation_id, role="user", content=body.content
    )
    # Launch agent response streaming as a background task.
    # The agent's response will stream via the SSE /events endpoint.
    background_tasks.add_task(_stream_agent_response, conversation_id, body.content)
    return MessageResponse.model_validate(msg)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
def get_messages(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[MessageResponse]:
    msgs = conversation_service.get_messages(db, conversation_id, limit=limit, offset=offset)
    return [MessageResponse.model_validate(m) for m in msgs]


@router.post("/{conversation_id}/steer", response_model=SteerResponse)
async def steer_conversation(conversation_id: str, body: SteerRequest):
    """Send a steering message to a running background task.

    The message is queued and picked up at the next turn boundary.
    """
    from backend.openloop.agents import agent_runner

    success = await agent_runner.steer(conversation_id, body.message)
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found, not a background task, or steering queue full",
        )
    return SteerResponse(status="queued", conversation_id=conversation_id)


@router.post("/{conversation_id}/close", response_model=ConversationResponse)
async def close_conversation(conversation_id: str, db: Session = Depends(get_db)) -> ConversationResponse:
    from backend.openloop.agents import agent_runner

    await agent_runner.close_conversation(db, conversation_id=conversation_id)
    conv = conversation_service.get_conversation(db, conversation_id)
    return ConversationResponse.model_validate(conv)


@router.post("/{conversation_id}/reopen", response_model=ConversationResponse)
def reopen_conversation(
    conversation_id: str, db: Session = Depends(get_db)
) -> ConversationResponse:
    conv = conversation_service.reopen_conversation(db, conversation_id)
    return ConversationResponse.model_validate(conv)


@router.get("/{conversation_id}/summaries", response_model=list[SummaryResponse])
def get_summaries(
    conversation_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[SummaryResponse]:
    summaries = conversation_service.get_summaries(db, conversation_id=conversation_id)
    return [SummaryResponse.model_validate(s) for s in summaries[offset : offset + limit]]
