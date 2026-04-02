"""Tests for the behavioral rule service (procedural memory).

Covers: create_rule, get_rule, list_rules, confirm_rule, override_rule,
apply_rules, deactivate_rule, delete_rule, and auto-deactivation logic.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, behavioral_rule_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(db: Session, name: str = "TestAgent"):
    return agent_service.create_agent(db, name=name)


def _make_rule(db: Session, agent_id: str, rule: str = "Always use dark mode", **kwargs):
    return behavioral_rule_service.create_rule(db, agent_id=agent_id, rule=rule, **kwargs)


# ---------------------------------------------------------------------------
# create_rule
# ---------------------------------------------------------------------------


class TestCreateRule:
    def test_creates_with_defaults(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)

        assert rule.id is not None
        assert rule.agent_id == agent.id
        assert rule.rule == "Always use dark mode"
        assert rule.confidence == 0.5
        assert rule.source_type == "correction"
        assert rule.is_active is True
        assert rule.apply_count == 0
        assert rule.last_applied is None

    def test_creates_with_custom_source_type(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id, source_type="validation")
        assert rule.source_type == "validation"

    def test_creates_with_conversation_id(self, db_session: Session):
        from backend.openloop.services import conversation_service, space_service

        agent = _make_agent(db_session)
        space = space_service.create_space(db_session, name="Test", template="project")
        conv = conversation_service.create_conversation(
            db_session, agent_id=agent.id, name="Test Conv", space_id=space.id
        )
        rule = _make_rule(
            db_session, agent.id, source_conversation_id=conv.id
        )
        assert rule.source_conversation_id == conv.id


# ---------------------------------------------------------------------------
# get_rule
# ---------------------------------------------------------------------------


class TestGetRule:
    def test_returns_by_id(self, db_session: Session):
        agent = _make_agent(db_session)
        created = _make_rule(db_session, agent.id)

        fetched = behavioral_rule_service.get_rule(db_session, created.id)
        assert fetched.id == created.id
        assert fetched.rule == created.rule

    def test_404_on_missing(self, db_session: Session):
        with pytest.raises(HTTPException) as exc_info:
            behavioral_rule_service.get_rule(db_session, "nonexistent-id")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# list_rules
# ---------------------------------------------------------------------------


class TestListRules:
    def test_sorted_by_confidence_desc(self, db_session: Session):
        agent = _make_agent(db_session)
        low = _make_rule(db_session, agent.id, rule="low confidence")
        high = _make_rule(db_session, agent.id, rule="high confidence")

        # Set confidence manually
        low.confidence = 0.3
        high.confidence = 0.9
        db_session.commit()

        rules = behavioral_rule_service.list_rules(db_session, agent_id=agent.id)
        assert len(rules) == 2
        assert rules[0].confidence >= rules[1].confidence
        assert rules[0].rule == "high confidence"

    def test_active_only_filter(self, db_session: Session):
        agent = _make_agent(db_session)
        _make_rule(db_session, agent.id, rule="active")
        inactive = _make_rule(db_session, agent.id, rule="inactive")
        behavioral_rule_service.deactivate_rule(db_session, inactive.id)

        # active_only=True (default)
        rules = behavioral_rule_service.list_rules(db_session, agent_id=agent.id)
        assert len(rules) == 1
        assert rules[0].rule == "active"

        # active_only=False
        all_rules = behavioral_rule_service.list_rules(
            db_session, agent_id=agent.id, active_only=False
        )
        assert len(all_rules) == 2


# ---------------------------------------------------------------------------
# confirm_rule
# ---------------------------------------------------------------------------


class TestConfirmRule:
    def test_increases_confidence(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)
        assert rule.confidence == 0.5

        updated = behavioral_rule_service.confirm_rule(db_session, rule.id)
        assert abs(updated.confidence - 0.6) < 0.001

    def test_caps_at_one(self, db_session: Session):
        """Confirming 6 times from 0.5 should cap at 1.0, not 1.1."""
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)

        for _ in range(6):
            rule = behavioral_rule_service.confirm_rule(db_session, rule.id)

        assert rule.confidence == 1.0

    def test_already_at_one(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)
        rule.confidence = 1.0
        db_session.commit()

        confirmed = behavioral_rule_service.confirm_rule(db_session, rule.id)
        assert confirmed.confidence == 1.0


# ---------------------------------------------------------------------------
# override_rule
# ---------------------------------------------------------------------------


class TestOverrideRule:
    def test_decreases_confidence(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)
        assert rule.confidence == 0.5

        updated = behavioral_rule_service.override_rule(db_session, rule.id)
        assert abs(updated.confidence - 0.3) < 0.001

    def test_asymmetry_override_stronger_than_confirm(self, db_session: Session):
        """One override (-0.2) does more damage than one confirm (+0.1)."""
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)  # starts at 0.5

        # One confirm then one override
        behavioral_rule_service.confirm_rule(db_session, rule.id)  # -> 0.6
        result = behavioral_rule_service.override_rule(db_session, rule.id)  # -> 0.4

        # Net effect is negative: 0.4 < 0.5
        assert result.confidence < 0.5

    def test_confidence_floor_at_zero(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)

        # Override many times
        for _ in range(10):
            rule = behavioral_rule_service.override_rule(db_session, rule.id)

        assert rule.confidence == 0.0

    def test_auto_deactivation(self, db_session: Session):
        """Override with apply_count >= 10 and confidence < 0.3 deactivates the rule."""
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)
        rule.apply_count = 15  # above the 10 threshold
        rule.confidence = 0.4  # one override will push to 0.2, below 0.3
        db_session.commit()

        result = behavioral_rule_service.override_rule(db_session, rule.id)
        assert result.confidence < 0.3
        assert result.is_active is False

    def test_no_auto_deactivation_below_apply_threshold(self, db_session: Session):
        """Low apply_count should NOT auto-deactivate even if confidence is low."""
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)
        rule.apply_count = 5  # below the 10 threshold
        rule.confidence = 0.4
        db_session.commit()

        result = behavioral_rule_service.override_rule(db_session, rule.id)
        assert result.confidence < 0.3
        assert result.is_active is True  # still active because apply_count < 10


# ---------------------------------------------------------------------------
# apply_rules
# ---------------------------------------------------------------------------


class TestApplyRules:
    def test_returns_active_rules(self, db_session: Session):
        agent = _make_agent(db_session)
        _make_rule(db_session, agent.id, rule="Rule A")
        _make_rule(db_session, agent.id, rule="Rule B")

        rules = behavioral_rule_service.apply_rules(db_session, agent_id=agent.id)
        assert len(rules) == 2

    def test_increments_apply_count(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)
        assert rule.apply_count == 0

        behavioral_rule_service.apply_rules(db_session, agent_id=agent.id)
        db_session.refresh(rule)
        assert rule.apply_count == 1

        behavioral_rule_service.apply_rules(db_session, agent_id=agent.id)
        db_session.refresh(rule)
        assert rule.apply_count == 2

    def test_sets_last_applied(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)
        assert rule.last_applied is None

        behavioral_rule_service.apply_rules(db_session, agent_id=agent.id)
        db_session.refresh(rule)
        assert rule.last_applied is not None

    def test_excludes_inactive(self, db_session: Session):
        agent = _make_agent(db_session)
        _make_rule(db_session, agent.id, rule="active")
        inactive = _make_rule(db_session, agent.id, rule="inactive")
        behavioral_rule_service.deactivate_rule(db_session, inactive.id)

        rules = behavioral_rule_service.apply_rules(db_session, agent_id=agent.id)
        assert len(rules) == 1
        assert rules[0].rule == "active"

    def test_sorted_by_confidence_desc(self, db_session: Session):
        agent = _make_agent(db_session)
        low = _make_rule(db_session, agent.id, rule="low")
        high = _make_rule(db_session, agent.id, rule="high")
        low.confidence = 0.3
        high.confidence = 0.9
        db_session.commit()

        rules = behavioral_rule_service.apply_rules(db_session, agent_id=agent.id)
        assert rules[0].confidence >= rules[1].confidence


# ---------------------------------------------------------------------------
# deactivate_rule
# ---------------------------------------------------------------------------


class TestDeactivateRule:
    def test_sets_is_active_false(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)
        assert rule.is_active is True

        deactivated = behavioral_rule_service.deactivate_rule(db_session, rule.id)
        assert deactivated.is_active is False


# ---------------------------------------------------------------------------
# delete_rule
# ---------------------------------------------------------------------------


class TestDeleteRule:
    def test_hard_deletes(self, db_session: Session):
        agent = _make_agent(db_session)
        rule = _make_rule(db_session, agent.id)

        behavioral_rule_service.delete_rule(db_session, rule.id)

        with pytest.raises(HTTPException) as exc_info:
            behavioral_rule_service.get_rule(db_session, rule.id)
        assert exc_info.value.status_code == 404

    def test_404_on_missing(self, db_session: Session):
        with pytest.raises(HTTPException) as exc_info:
            behavioral_rule_service.delete_rule(db_session, "nonexistent")
        assert exc_info.value.status_code == 404
