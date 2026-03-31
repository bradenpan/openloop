from datetime import datetime

from contract.enums import GrantLevel, Operation
from pydantic import BaseModel, ConfigDict

__all__ = [
    "AgentCreate",
    "AgentUpdate",
    "AgentResponse",
    "AgentPermissionSet",
    "AgentPermissionResponse",
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


class AgentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    system_prompt: str | None
    default_model: str
    tools: list | None
    mcp_tools: list | None
    status: str
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
