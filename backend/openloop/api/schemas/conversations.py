from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = [
    "ConversationCreate",
    "ConversationResponse",
    "MessageCreate",
    "MessageResponse",
    "SteerRequest",
    "SteerResponse",
    "SummaryCreate",
    "SummaryResponse",
]


class ConversationCreate(BaseModel):
    agent_id: str
    name: str
    space_id: str | None = None
    model_override: str | None = None


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    space_id: str | None
    agent_id: str
    name: str
    status: str
    model_override: str | None
    sdk_session_id: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None


class SteerRequest(BaseModel):
    message: str


class SteerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str
    conversation_id: str


class MessageCreate(BaseModel):
    content: str


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    role: str
    content: str
    tool_calls: dict | None
    created_at: datetime


class SummaryCreate(BaseModel):
    summary: str
    decisions: list[str] | None = None
    open_questions: list[str] | None = None
    is_checkpoint: bool = False
    is_meta_summary: bool = False


class SummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    conversation_id: str
    space_id: str | None
    summary: str
    decisions: list[str] | None
    open_questions: list[str] | None
    is_checkpoint: bool
    is_meta_summary: bool
    consolidated_into: str | None
    created_at: datetime
