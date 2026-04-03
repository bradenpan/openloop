from pydantic import BaseModel, ConfigDict

__all__ = [
    "AutonomousLaunchRequest",
    "AutonomousLaunchResponse",
    "TaskListResponse",
    "TaskListUpdateRequest",
]


class AutonomousLaunchRequest(BaseModel):
    goal: str
    constraints: str | None = None
    token_budget: int | None = None
    time_budget: int | None = None


class AutonomousLaunchResponse(BaseModel):
    conversation_id: str
    task_id: str


class TaskListResponse(BaseModel):
    task_list: list | None = None
    task_list_version: int = 0
    completed_count: int = 0
    total_count: int = 0


class TaskListUpdateRequest(BaseModel):
    task_list: list
