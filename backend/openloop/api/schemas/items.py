from datetime import datetime

from contract.enums import ItemType, LinkType
from pydantic import BaseModel, ConfigDict

__all__ = [
    "ItemCreate",
    "ItemUpdate",
    "ItemResponse",
    "ItemMove",
    "ItemEventResponse",
    "RecordChildrenResponse",
    "ItemLinkCreate",
    "ItemLinkResponse",
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
    parent_item_id: str | None = None
    is_agent_task: bool = False
    is_done: bool = False


class ItemUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    priority: int | None = None
    sort_position: float | None = None
    custom_fields: dict | None = None
    due_date: datetime | None = None
    assigned_agent_id: str | None = None
    parent_item_id: str | None = None
    is_agent_task: bool | None = None
    is_done: bool | None = None


class ItemMove(BaseModel):
    stage: str


class ItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    space_id: str
    item_type: ItemType
    is_agent_task: bool
    is_done: bool
    title: str
    description: str | None
    stage: str | None
    priority: int | None
    sort_position: float
    custom_fields: dict | None
    parent_item_id: str | None
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


class RecordChildrenResponse(BaseModel):
    record: ItemResponse
    child_records: list[ItemResponse]
    linked_items: list[ItemResponse]


class ItemLinkCreate(BaseModel):
    target_item_id: str
    link_type: LinkType = LinkType.RELATED_TO


class ItemLinkResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_item_id: str
    target_item_id: str
    link_type: LinkType
    created_at: datetime
