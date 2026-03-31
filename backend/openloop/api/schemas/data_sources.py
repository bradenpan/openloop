from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["DataSourceCreate", "DataSourceUpdate", "DataSourceResponse"]


class DataSourceCreate(BaseModel):
    space_id: str
    name: str
    source_type: str
    config: dict | None = None
    refresh_schedule: str | None = None


class DataSourceUpdate(BaseModel):
    name: str | None = None
    config: dict | None = None
    refresh_schedule: str | None = None
    status: str | None = None


class DataSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    space_id: str
    source_type: str
    name: str
    config: dict | None
    refresh_schedule: str | None
    status: str
    created_at: datetime
    updated_at: datetime
