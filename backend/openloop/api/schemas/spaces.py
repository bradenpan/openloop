from datetime import datetime

from contract.enums import DefaultView, SpaceTemplate
from pydantic import BaseModel, ConfigDict

__all__ = ["SpaceCreate", "SpaceUpdate", "SpaceResponse"]


class SpaceCreate(BaseModel):
    name: str
    template: SpaceTemplate
    description: str | None = None


class SpaceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    board_enabled: bool | None = None
    default_view: DefaultView | None = None
    board_columns: list[str] | None = None
    custom_field_schema: list[dict] | None = None


class SpaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    parent_space_id: str | None
    name: str
    description: str | None
    template: str
    board_enabled: bool
    default_view: str | None
    board_columns: list[str] | None
    custom_field_schema: list[dict] | None
    created_at: datetime
    updated_at: datetime
