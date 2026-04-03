from pydantic import BaseModel, ConfigDict

__all__ = [
    "DashboardResponse",
]


class DashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_spaces: int
    open_task_count: int
    pending_approvals: int
    active_conversations: int
    unread_notifications: int
