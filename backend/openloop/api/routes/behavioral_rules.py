from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import (
    BehavioralRuleCreate,
    BehavioralRuleResponse,
    BehavioralRuleUpdate,
)
from backend.openloop.database import get_db
from backend.openloop.services import behavioral_rule_service

router = APIRouter(prefix="/api/v1/agents/{agent_id}/rules", tags=["behavioral-rules"])


@router.get("", response_model=list[BehavioralRuleResponse])
def list_rules(
    agent_id: str,
    active_only: bool = Query(True),
    db: Session = Depends(get_db),
) -> list[BehavioralRuleResponse]:
    rules = behavioral_rule_service.list_rules(db, agent_id=agent_id, active_only=active_only)
    return [BehavioralRuleResponse.model_validate(r) for r in rules]


@router.post("", response_model=BehavioralRuleResponse, status_code=201)
def create_rule(
    agent_id: str,
    body: BehavioralRuleCreate,
    db: Session = Depends(get_db),
) -> BehavioralRuleResponse:
    rule = behavioral_rule_service.create_rule(
        db,
        agent_id=agent_id,
        rule=body.rule,
        source_type=body.source_type.value,
        source_conversation_id=body.source_conversation_id,
        origin=body.origin.value if body.origin else "user_confirmed",
    )
    return BehavioralRuleResponse.model_validate(rule)


@router.patch("/{rule_id}", response_model=BehavioralRuleResponse)
def update_rule(
    agent_id: str,
    rule_id: str,
    body: BehavioralRuleUpdate,
    db: Session = Depends(get_db),
) -> BehavioralRuleResponse:
    # Verify rule belongs to this agent
    existing = behavioral_rule_service.get_rule(db, rule_id)
    if existing.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    updates = body.model_dump(exclude_unset=True)
    rule = behavioral_rule_service.update_rule(db, rule_id, **updates)
    return BehavioralRuleResponse.model_validate(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(agent_id: str, rule_id: str, db: Session = Depends(get_db)) -> None:
    # Verify rule belongs to this agent
    existing = behavioral_rule_service.get_rule(db, rule_id)
    if existing.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Rule not found")
    behavioral_rule_service.delete_rule(db, rule_id)
