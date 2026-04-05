from datetime import UTC, datetime

from contract.enums import ConversationStatus
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import (
    Agent,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    Space,
)


def create_conversation(
    db: Session,
    *,
    agent_id: str,
    name: str,
    space_id: str | None = None,
    model_override: str | None = None,
) -> Conversation:
    """Start a new conversation with an agent."""
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if space_id:
        space = db.query(Space).filter(Space.id == space_id).first()
        if not space:
            raise HTTPException(status_code=404, detail="Space not found")

    conversation = Conversation(
        space_id=space_id,
        agent_id=agent_id,
        name=name,
        status=ConversationStatus.ACTIVE,
        model_override=model_override,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def get_conversation(db: Session, conversation_id: str) -> Conversation:
    """Get a conversation by ID, or 404."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conv


def list_conversations(
    db: Session,
    *,
    space_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Conversation]:
    """List conversations with optional filters. Cross-space if no space_id."""
    query = db.query(Conversation)
    if space_id is not None:
        query = query.filter(Conversation.space_id == space_id)
    if status is not None:
        query = query.filter(Conversation.status == status)
    return query.order_by(Conversation.updated_at.desc()).offset(offset).limit(limit).all()


def close_conversation(db: Session, conversation_id: str) -> Conversation:
    """Close a conversation. Requires status='active'."""
    conv = get_conversation(db, conversation_id)
    if conv.status != "active":
        raise HTTPException(
            status_code=409, detail=f"Cannot close conversation with status '{conv.status}'"
        )
    conv.status = ConversationStatus.CLOSED
    conv.closed_at = datetime.now(UTC).replace(tzinfo=None)
    db.commit()
    db.refresh(conv)
    return conv


def reopen_conversation(db: Session, conversation_id: str) -> Conversation:
    """Reopen a closed or interrupted conversation."""
    conv = get_conversation(db, conversation_id)
    if conv.status == "active":
        raise HTTPException(status_code=409, detail="Conversation is already active")
    conv.status = ConversationStatus.ACTIVE
    conv.closed_at = None
    db.commit()
    db.refresh(conv)
    return conv


def update_conversation(db: Session, conversation_id: str, **kwargs) -> Conversation:
    """Update conversation fields (name, model_override, sdk_session_id, status)."""
    conv = get_conversation(db, conversation_id)
    updatable = {"name", "model_override", "sdk_session_id", "status"}
    if "status" in kwargs and kwargs["status"] is not None:
        valid = {s.value for s in ConversationStatus}
        if kwargs["status"] not in valid:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status '{kwargs['status']}'. Valid: {sorted(valid)}",
            )
    for field, value in kwargs.items():
        if field in updatable:
            setattr(conv, field, value)
    db.commit()
    db.refresh(conv)
    return conv


# --- Messages ---


def add_message(
    db: Session,
    *,
    conversation_id: str,
    role: str,
    content: str,
    tool_calls: dict | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> ConversationMessage:
    """Add a message to a conversation."""
    get_conversation(db, conversation_id)  # Verify exists
    msg = ConversationMessage(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_calls=tool_calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


def get_messages(
    db: Session,
    conversation_id: str,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[ConversationMessage]:
    """Get messages for a conversation, ordered by creation time, with pagination."""
    get_conversation(db, conversation_id)  # Verify exists
    return (
        db.query(ConversationMessage)
        .filter(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )


# --- Summaries ---


def add_summary(
    db: Session,
    *,
    conversation_id: str,
    summary: str,
    decisions: list | None = None,
    open_questions: list | None = None,
    is_checkpoint: bool = False,
) -> ConversationSummary:
    """Add a summary to a conversation."""
    conv = get_conversation(db, conversation_id)
    entry = ConversationSummary(
        conversation_id=conversation_id,
        space_id=conv.space_id,
        summary=summary,
        decisions=decisions,
        open_questions=open_questions,
        is_checkpoint=is_checkpoint,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_summaries(
    db: Session,
    *,
    conversation_id: str | None = None,
    space_id: str | None = None,
    include_checkpoints: bool = True,
) -> list[ConversationSummary]:
    """Get summaries, optionally filtered."""
    query = db.query(ConversationSummary)
    if conversation_id is not None:
        query = query.filter(ConversationSummary.conversation_id == conversation_id)
    if space_id is not None:
        query = query.filter(ConversationSummary.space_id == space_id)
    if not include_checkpoints:
        query = query.filter(ConversationSummary.is_checkpoint == False)  # noqa: E712
    return query.order_by(ConversationSummary.created_at.desc()).all()
