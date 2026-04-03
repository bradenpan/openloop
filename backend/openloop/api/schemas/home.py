from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = [
    "DashboardResponse",
    "MorningBriefRun",
    "MorningBriefAgent",
    "MorningBriefResponse",
]


class DashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    total_spaces: int
    open_task_count: int
    pending_approvals: int
    active_conversations: int
    unread_notifications: int


class MorningBriefRun(BaseModel):
    task_id: str
    goal: str | None = None
    run_summary: str | None = None
    status: str
    completed_count: int = 0
    total_count: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None


class MorningBriefAgent(BaseModel):
    agent_id: str
    agent_name: str
    runs: list[MorningBriefRun]


class MorningBriefResponse(BaseModel):
    agents: list[MorningBriefAgent]
    pending_approvals_count: int
    failed_tasks_count: int
    since: datetime | None = None
