from pydantic import BaseModel

__all__ = [
    "BackupStatusResponse",
    "SystemStatusResponse",
    "EmergencyStopResponse",
    "SystemResumeResponse",
]


class BackupStatusResponse(BaseModel):
    last_backup_at: str | None = None
    hours_since_backup: int | None = None
    needs_backup: bool


class SystemStatusResponse(BaseModel):
    paused: bool
    active_sessions: int


class EmergencyStopResponse(BaseModel):
    paused: bool
    tasks_interrupted: int
    interrupted_task_ids: list[str]


class SystemResumeResponse(BaseModel):
    paused: bool
