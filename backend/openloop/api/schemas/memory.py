from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["MemoryCreate", "MemoryUpdate", "MemoryResponse"]


class MemoryCreate(BaseModel):
    namespace: str
    key: str
    value: str
    tags: list[str] | None = None
    source: str = "user"
    importance: float = 0.5
    category: str | None = None


class MemoryUpdate(BaseModel):
    value: str | None = None
    tags: list[str] | None = None
    source: str | None = None
    importance: float | None = None
    category: str | None = None


class MemoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    namespace: str
    key: str
    value: str
    tags: list | None
    source: str
    importance: float
    access_count: int
    last_accessed: datetime | None
    valid_from: datetime
    valid_until: datetime | None
    archived_at: datetime | None
    category: str | None
    created_at: datetime
    updated_at: datetime
