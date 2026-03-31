from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["NotificationResponse"]


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    type: str
    title: str
    body: str | None
    space_id: str | None
    conversation_id: str | None
    is_read: bool
    created_at: datetime
