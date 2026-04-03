from datetime import datetime

from contract.enums import RuleOrigin, RuleSourceType
from pydantic import BaseModel, ConfigDict

__all__ = [
    "BehavioralRuleCreate",
    "BehavioralRuleUpdate",
    "BehavioralRuleResponse",
]


class BehavioralRuleCreate(BaseModel):
    rule: str
    source_type: RuleSourceType = RuleSourceType.CORRECTION
    source_conversation_id: str | None = None
    origin: RuleOrigin | None = RuleOrigin.USER_CONFIRMED


class BehavioralRuleUpdate(BaseModel):
    rule: str | None = None
    is_active: bool | None = None
    origin: RuleOrigin | None = None


class BehavioralRuleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    agent_id: str
    rule: str
    source_type: str
    origin: str
    source_conversation_id: str | None
    confidence: float
    apply_count: int
    last_applied: datetime | None
    is_active: bool
    created_at: datetime
    updated_at: datetime
