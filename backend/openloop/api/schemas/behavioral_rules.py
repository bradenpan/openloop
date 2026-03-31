from datetime import datetime

from pydantic import BaseModel, ConfigDict

from contract.enums import RuleSourceType

__all__ = [
    "BehavioralRuleCreate",
    "BehavioralRuleUpdate",
    "BehavioralRuleResponse",
]


class BehavioralRuleCreate(BaseModel):
    agent_id: str
    rule: str
    source_type: RuleSourceType = RuleSourceType.CORRECTION
    source_conversation_id: str | None = None


class BehavioralRuleUpdate(BaseModel):
    rule: str | None = None
    is_active: bool | None = None


class BehavioralRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    rule: str
    source_type: str
    source_conversation_id: str | None
    confidence: float
    apply_count: int
    last_applied: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
