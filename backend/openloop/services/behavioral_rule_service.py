"""Service for managing behavioral rules (procedural memory).

Behavioral rules capture learned agent behaviors from corrections and validations.
Confidence adjusts asymmetrically: confirmations boost slowly, overrides decay faster.
"""

from datetime import UTC, datetime

from contract.enums import RuleSourceType
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import BehavioralRule

_VALID_SOURCE_TYPES = {e.value for e in RuleSourceType}


def create_rule(
    db: Session,
    *,
    agent_id: str,
    rule: str,
    source_type: str = "correction",
    source_conversation_id: str | None = None,
) -> BehavioralRule:
    """Create a new behavioral rule for an agent."""
    if source_type not in _VALID_SOURCE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid source_type '{source_type}'. Must be one of: {sorted(_VALID_SOURCE_TYPES)}",
        )
    entry = BehavioralRule(
        agent_id=agent_id,
        rule=rule,
        source_type=source_type,
        source_conversation_id=source_conversation_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_rule(db: Session, rule_id: str) -> BehavioralRule:
    """Get a behavioral rule by ID, or 404."""
    entry = db.query(BehavioralRule).filter(BehavioralRule.id == rule_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Behavioral rule not found")
    return entry


def list_rules(
    db: Session,
    *,
    agent_id: str,
    active_only: bool = True,
) -> list[BehavioralRule]:
    """List behavioral rules for an agent, sorted by confidence descending."""
    query = db.query(BehavioralRule).filter(BehavioralRule.agent_id == agent_id)
    if active_only:
        query = query.filter(BehavioralRule.is_active.is_(True))
    return query.order_by(BehavioralRule.confidence.desc()).all()


def confirm_rule(db: Session, rule_id: str) -> BehavioralRule:
    """Confirm a rule: increase confidence by 0.1, capped at 1.0."""
    entry = get_rule(db, rule_id)
    entry.confidence = min(entry.confidence + 0.1, 1.0)
    db.commit()
    db.refresh(entry)
    return entry


def override_rule(db: Session, rule_id: str) -> BehavioralRule:
    """Override a rule: decrease confidence by 0.2 (asymmetric decay).

    If confidence drops below 0.3 AND rule has been applied at least 10 times,
    automatically deactivate the rule.
    """
    entry = get_rule(db, rule_id)
    entry.confidence = max(entry.confidence - 0.2, 0.0)
    if entry.confidence < 0.3 and entry.apply_count >= 10:
        entry.is_active = False
    db.commit()
    db.refresh(entry)
    return entry


def apply_rules(db: Session, *, agent_id: str, read_only: bool = False) -> list[BehavioralRule]:
    """Return active rules for an agent, sorted by confidence descending.

    Unless read_only=True, increments apply_count and sets last_applied.
    Use read_only=True for estimation/dry-run paths to avoid inflating counters.
    """
    rules = (
        db.query(BehavioralRule)
        .filter(
            BehavioralRule.agent_id == agent_id,
            BehavioralRule.is_active.is_(True),
        )
        .order_by(BehavioralRule.confidence.desc())
        .all()
    )
    if not read_only:
        now = datetime.now(UTC)
        for rule in rules:
            rule.apply_count += 1
            rule.last_applied = now
        db.commit()
    return rules


def deactivate_rule(db: Session, rule_id: str) -> BehavioralRule:
    """Deactivate a rule without deleting it."""
    entry = get_rule(db, rule_id)
    entry.is_active = False
    db.commit()
    db.refresh(entry)
    return entry


def delete_rule(db: Session, rule_id: str) -> None:
    """Hard-delete a behavioral rule by ID, or 404."""
    entry = get_rule(db, rule_id)
    db.delete(entry)
    db.commit()
