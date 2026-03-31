from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["TodoCreate", "TodoUpdate", "TodoResponse", "TodoPromote"]


class TodoCreate(BaseModel):
    space_id: str
    title: str
    due_date: datetime | None = None


class TodoUpdate(BaseModel):
    title: str | None = None
    is_done: bool | None = None
    due_date: datetime | None = None
    sort_position: float | None = None


class TodoPromote(BaseModel):
    stage: str | None = None


class TodoResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    space_id: str
    title: str
    is_done: bool
    due_date: datetime | None
    sort_position: float
    created_by: str
    source_conversation_id: str | None
    promoted_to_item_id: str | None
    created_at: datetime
    updated_at: datetime
