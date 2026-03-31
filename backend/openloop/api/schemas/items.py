from datetime import datetime

from contract.enums import ItemType
from pydantic import BaseModel, ConfigDict

__all__ = [
    "ItemCreate",
    "ItemUpdate",
    "ItemResponse",
    "ItemMove",
    "ItemEventResponse",
]


class ItemCreate(BaseModel):
    space_id: str
    title: str
    item_type: ItemType = ItemType.TASK
    description: str | None = None
    stage: str | None = None
    priority: int | None = None
    custom_fields: dict | None = None
    due_date: datetime | None = None
    assigned_agent_id: str | None = None
    parent_record_id: str | None = None
    is_agent_task: bool = False


class ItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    sort_position: float | None = None
    custom_fields: dict | None = None
    due_date: datetime | None = None
    assigned_agent_id: str | None = None
    parent_record_id: str | None = None
    is_agent_task: bool | None = None


class ItemMove(BaseModel):
    stage: str


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    space_id: str
    item_type: str
    is_agent_task: bool
    title: str
    description: str | None
    stage: str | None
    priority: int | None
    sort_position: float
    custom_fields: dict | None
    parent_record_id: str | None
    assigned_agent_id: str | None
    due_date: datetime | None
    created_by: str
    source_conversation_id: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime


class ItemEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    item_id: str
    event_type: str
    old_value: str | None
    new_value: str | None
    triggered_by: str
    created_at: datetime
