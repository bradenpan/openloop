from pydantic import BaseModel

__all__ = ["BackupStatusResponse"]


class BackupStatusResponse(BaseModel):
    last_backup_at: str | None = None
    hours_since_backup: int | None = None
    needs_backup: bool
