from datetime import datetime

from contract.enums import GrantLevel, Operation, PermissionRequestStatus
from pydantic import BaseModel, ConfigDict, field_validator

__all__ = [
    "AgentCreate",
    "AgentUpdate",
    "AgentResponse",
    "AgentPermissionSet",
    "AgentPermissionResponse",
    "PermissionRequestUpdate",
    "PermissionRequestResponse",
    "RunningSessionResponse",
]


class AgentCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str | None = None
    default_model: str = "sonnet"
    tools: list[str] | None = None
    mcp_tools: list[str] | None = None
    space_ids: list[str] | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    default_model: str | None = None
    tools: list[str] | None = None
    mcp_tools: list[str] | None = None
    status: str | None = None
    max_spawn_depth: int | None = None
    heartbeat_enabled: bool | None = None
    heartbeat_cron: str | None = None


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    system_prompt: str | None
    default_model: str
    tools: list[str] | None
    mcp_tools: list[str] | None
    skill_path: str | None = None
    status: str
    max_spawn_depth: int = 1
    heartbeat_enabled: bool = False
    heartbeat_cron: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentPermissionSet(BaseModel):
    agent_id: str
    resource_pattern: str
    operation: Operation
    grant_level: GrantLevel


class AgentPermissionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    resource_pattern: str
    operation: str
    grant_level: str


class PermissionRequestUpdate(BaseModel):
    status: PermissionRequestStatus

    @field_validator("status")
    @classmethod
    def status_must_be_resolution(cls, v: PermissionRequestStatus) -> PermissionRequestStatus:
        if v not in (PermissionRequestStatus.APPROVED, PermissionRequestStatus.DENIED):
            raise ValueError("status must be 'approved' or 'denied'")
        return v


class PermissionRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    conversation_id: str | None
    tool_name: str
    resource: str
    operation: str
    tool_input: dict | None
    status: str
    resolved_by: str | None
    created_at: datetime
    resolved_at: datetime | None


class RunningSessionResponse(BaseModel):
    conversation_id: str
    agent_id: str
    space_id: str | None
    sdk_session_id: str | None
    status: str
    started_at: str
    last_activity: str
    # Phase 9.4a: enriched fields for active agents panel
    run_type: str | None = None
    background_task_id: str | None = None
    instruction: str | None = None
    completed_count: int | None = None
    total_count: int | None = None
    token_budget: int | None = None
