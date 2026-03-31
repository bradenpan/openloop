from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["MemoryCreate", "MemoryUpdate", "MemoryResponse"]


class MemoryCreate(BaseModel):
    namespace: str
    key: str
    value: str
    tags: list[str] | None = None
    source: str = "user"


class MemoryUpdate(BaseModel):
    value: str | None = None
    tags: list[str] | None = None
    source: str | None = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    namespace: str
    key: str
    value: str
    tags: list | None
    source: str
    created_at: datetime
    updated_at: datetime
