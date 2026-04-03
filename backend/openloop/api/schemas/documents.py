from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = ["DocumentCreate", "DocumentUpdate", "DocumentResponse", "ScanResponse"]


class DocumentCreate(BaseModel):
    space_id: str
    title: str
    source: str = "local"
    local_path: str | None = None
    drive_file_id: str | None = None
    drive_folder_id: str | None = None
    tags: list[str] | None = None

    @field_validator("local_path")
    @classmethod
    def reject_path_traversal(cls, v: str | None) -> str | None:
        if v is not None and ".." in v:
            raise ValueError("local_path must not contain '..'")
        return v


class DocumentUpdate(BaseModel):
    title: str | None = None
    tags: list[str] | None = None


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    space_id: str
    title: str
    source: str
    local_path: str | None
    drive_file_id: str | None
    drive_folder_id: str | None
    file_size: int | None
    mime_type: str | None
    tags: list[str] | None
    indexed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ScanResponse(BaseModel):
    new_count: int
