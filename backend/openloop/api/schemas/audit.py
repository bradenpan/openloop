from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["AuditLogResponse"]


class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    conversation_id: str | None
    background_task_id: str | None
    tool_name: str
    action: str
    resource_id: str | None
    input_summary: str | None
    timestamp: datetime
