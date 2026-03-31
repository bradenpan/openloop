from datetime import datetime

from pydantic import BaseModel, ConfigDict

from contract.enums import WidgetSize, WidgetType

__all__ = ["WidgetCreate", "WidgetUpdate", "WidgetResponse", "LayoutResponse", "LayoutBulkReplace"]


class WidgetCreate(BaseModel):
    widget_type: WidgetType
    position: int | None = None
    size: WidgetSize = WidgetSize.MEDIUM
    config: dict | None = None


class WidgetUpdate(BaseModel):
    size: WidgetSize | None = None
    config: dict | None = None
    position: int | None = None


class WidgetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    space_id: str
    widget_type: str
    position: int
    size: str
    config: dict | None
    created_at: datetime
    updated_at: datetime


class LayoutResponse(BaseModel):
    widgets: list[WidgetResponse]


class LayoutBulkReplace(BaseModel):
    widgets: list[WidgetCreate]
