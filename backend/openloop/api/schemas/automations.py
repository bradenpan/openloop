from datetime import datetime

from contract.enums import AutomationTriggerType
from croniter import croniter
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

__all__ = [
    "AutomationCreate",
    "AutomationUpdate",
    "AutomationRunResponse",
    "AutomationResponse",
    "TriggerResponse",
]


class AutomationCreate(BaseModel):
    name: str
    description: str | None = None
    agent_id: str
    instruction: str
    trigger_type: AutomationTriggerType
    cron_expression: str | None = None
    space_id: str | None = None
    model_override: str | None = None
    enabled: bool = True

    @field_validator("cron_expression")
    @classmethod
    def validate_cron_expression(cls, v: str | None) -> str | None:
        if v is not None and not croniter.is_valid(v):
            raise ValueError("Invalid cron expression")
        return v

    @model_validator(mode="after")
    def validate_cron_requires_expression(self):
        if self.trigger_type == AutomationTriggerType.CRON and self.cron_expression is None:
            raise ValueError("cron_expression is required when trigger_type is 'cron'")
        return self


class AutomationUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    agent_id: str | None = None
    instruction: str | None = None
    trigger_type: AutomationTriggerType | None = None
    cron_expression: str | None = None
    space_id: str | None = None
    model_override: str | None = None
    enabled: bool | None = None

    @field_validator("cron_expression")
    @classmethod
    def validate_cron_expression(cls, v: str | None) -> str | None:
        if v is not None and not croniter.is_valid(v):
            raise ValueError("Invalid cron expression")
        return v

    @model_validator(mode="after")
    def validate_cron_update(self) -> "AutomationUpdate":
        if "trigger_type" in self.model_fields_set:
            if self.trigger_type == AutomationTriggerType.CRON:
                if "cron_expression" not in self.model_fields_set and self.cron_expression is None:
                    raise ValueError("cron_expression is required when setting trigger_type to cron")
        return self


class AutomationRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    automation_id: str
    background_task_id: str | None
    status: str
    result_summary: str | None
    error: str | None
    started_at: datetime
    completed_at: datetime | None


class AutomationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    description: str | None
    space_id: str | None
    agent_id: str
    instruction: str
    trigger_type: str
    cron_expression: str | None
    event_source: str | None
    event_filter: dict | None
    model_override: str | None
    enabled: bool
    last_run_at: datetime | None
    last_run_status: str | None
    created_at: datetime
    updated_at: datetime
    runs: list[AutomationRunResponse] = []


class TriggerResponse(BaseModel):
    run: AutomationRunResponse
