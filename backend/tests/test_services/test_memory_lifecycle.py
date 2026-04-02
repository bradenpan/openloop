"""Tests for Phase 7.1a memory lifecycle management functions."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.openloop.db.models import (
    Agent,
    BehavioralRule,
    Conversation,
    ConversationSummary,
    MemoryEntry,
    Space,
)
from backend.openloop.services import memory_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_space(db: Session, name: str = "Test Space") -> Space:
    space = Space(name=name, template="project")
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


def _create_agent(db: Session, name: str = "Test Agent") -> Agent:
    agent = Agent(name=name, status="idle")
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _create_conversation(
    db: Session, space: Space, agent: Agent, status: str = "active"
) -> Conversation:
    conv = Conversation(
        space_id=space.id, agent_id=agent.id, name="test conv", status=status
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


# ---------------------------------------------------------------------------
# auto_archive_superseded tests
# ---------------------------------------------------------------------------


def test_auto_archive_superseded_archives_old(db_session: Session):
    """Entries superseded 90+ days ago should be archived."""
    entry = MemoryEntry(
        namespace="global",
        key="old-fact",
        value="outdated",
        valid_until=datetime.now(UTC) - timedelta(days=91),
    )
    db_session.add(entry)
    db_session.commit()

    count = memory_service.auto_archive_superseded(db_session)
    assert count == 1

    db_session.refresh(entry)
    assert entry.archived_at is not None


def test_auto_archive_superseded_skips_recent(db_session: Session):
    """Entries superseded less than 90 days ago should NOT be archived."""
    entry = MemoryEntry(
        namespace="global",
        key="recent-fact",
        value="still relevant",
        valid_until=datetime.now(UTC) - timedelta(days=30),
    )
    db_session.add(entry)
    db_session.commit()

    count = memory_service.auto_archive_superseded(db_session)
    assert count == 0

    db_session.refresh(entry)
    assert entry.archived_at is None


def test_auto_archive_superseded_skips_already_archived(db_session: Session):
    """Already-archived entries should not be re-processed."""
    entry = MemoryEntry(
        namespace="global",
        key="already-archived",
        value="done",
        valid_until=datetime.now(UTC) - timedelta(days=100),
        archived_at=datetime.now(UTC) - timedelta(days=5),
    )
    db_session.add(entry)
    db_session.commit()

    count = memory_service.auto_archive_superseded(db_session)
    assert count == 0


def test_auto_archive_superseded_skips_non_superseded(db_session: Session):
    """Active entries (valid_until IS NULL) should not be touched."""
    entry = MemoryEntry(
        namespace="global",
        key="active-fact",
        value="current",
    )
    db_session.add(entry)
    db_session.commit()

    count = memory_service.auto_archive_superseded(db_session)
    assert count == 0

    db_session.refresh(entry)
    assert entry.archived_at is None


# ---------------------------------------------------------------------------
# get_memory_health tests
# ---------------------------------------------------------------------------


def test_get_memory_health_empty(db_session: Session):
    space = _create_space(db_session)
    health = memory_service.get_memory_health(db_session, space.id)
    assert health == {
        "active_facts": 0,
        "archived_facts": 0,
        "active_rules": 0,
        "inactive_rules": 0,
    }


def test_get_memory_health_counts(db_session: Session):
    space = _create_space(db_session)
    ns = f"space:{space.id}"

    # Active facts
    db_session.add(MemoryEntry(namespace=ns, key="f1", value="v1"))
    db_session.add(MemoryEntry(namespace=ns, key="f2", value="v2"))
    # Archived fact
    db_session.add(
        MemoryEntry(
            namespace=ns, key="f3", value="v3", archived_at=datetime.now(UTC)
        )
    )
    # Superseded fact (counts as neither active nor archived)
    db_session.add(
        MemoryEntry(
            namespace=ns, key="f4", value="v4", valid_until=datetime.now(UTC)
        )
    )

    # Agent with rules linked to space via conversation
    agent = _create_agent(db_session)
    _create_conversation(db_session, space, agent)
    db_session.add(
        BehavioralRule(agent_id=agent.id, rule="do X", source_type="correction")
    )
    db_session.add(
        BehavioralRule(
            agent_id=agent.id, rule="do Y", source_type="correction", is_active=False
        )
    )
    db_session.commit()

    health = memory_service.get_memory_health(db_session, space.id)
    assert health["active_facts"] == 2
    assert health["archived_facts"] == 1
    assert health["active_rules"] == 1
    assert health["inactive_rules"] == 1


# ---------------------------------------------------------------------------
# apply_consolidation_report tests
# ---------------------------------------------------------------------------


def test_apply_consolidation_merges(db_session: Session):
    space = _create_space(db_session)
    ns = f"space:{space.id}"

    e1 = MemoryEntry(namespace=ns, key="f1", value="fact 1")
    e2 = MemoryEntry(namespace=ns, key="f2", value="fact 2")
    db_session.add_all([e1, e2])
    db_session.commit()

    report = {
        "merges": [
            {
                "source_ids": [e1.id, e2.id],
                "merged_value": "merged fact",
                "reason": "duplicates",
            }
        ],
        "stale": [],
    }

    result = memory_service.apply_consolidation_report(db_session, space.id, report)
    assert result["merged"] == 1
    assert result["archived"] == 0

    # Source entries should be superseded
    db_session.refresh(e1)
    db_session.refresh(e2)
    assert e1.valid_until is not None
    assert e2.valid_until is not None

    # Merged entry should exist
    merged = (
        db_session.query(MemoryEntry)
        .filter(MemoryEntry.namespace == ns, MemoryEntry.source == "consolidation")
        .first()
    )
    assert merged is not None
    assert merged.value == "merged fact"


def test_apply_consolidation_stale(db_session: Session):
    space = _create_space(db_session)
    ns = f"space:{space.id}"

    e1 = MemoryEntry(namespace=ns, key="stale1", value="old stuff")
    db_session.add(e1)
    db_session.commit()

    report = {
        "merges": [],
        "stale": [{"id": e1.id, "reason": "zero access"}],
    }

    result = memory_service.apply_consolidation_report(db_session, space.id, report)
    assert result["archived"] == 1

    db_session.refresh(e1)
    assert e1.archived_at is not None


# ---------------------------------------------------------------------------
# Behavioral rule auto-demotion (via context assembler)
# ---------------------------------------------------------------------------


def test_auto_demotion_in_context_assembler(db_session: Session):
    """Rules with confidence < 0.3 and apply_count >= 10 should be deactivated."""
    from backend.openloop.agents.context_assembler import _build_behavioral_rules_section

    agent = _create_agent(db_session)

    # Low-confidence, high-apply rule — should be demoted
    rule1 = BehavioralRule(
        agent_id=agent.id,
        rule="demote me",
        source_type="correction",
        confidence=0.2,
        apply_count=15,
        is_active=True,
    )
    # Normal rule — should be kept
    rule2 = BehavioralRule(
        agent_id=agent.id,
        rule="keep me",
        source_type="correction",
        confidence=0.8,
        apply_count=5,
        is_active=True,
    )
    db_session.add_all([rule1, rule2])
    db_session.commit()

    section = _build_behavioral_rules_section(db_session, agent.id, read_only=True)

    # rule1 should be demoted
    db_session.refresh(rule1)
    assert rule1.is_active is False

    # rule2 should remain
    db_session.refresh(rule2)
    assert rule2.is_active is True

    # Output should only contain the kept rule
    assert "keep me" in section
    assert "demote me" not in section


def test_no_demotion_for_low_apply_count(db_session: Session):
    """Rules with low confidence but low apply_count should NOT be demoted."""
    from backend.openloop.agents.context_assembler import _build_behavioral_rules_section

    agent = _create_agent(db_session)

    rule = BehavioralRule(
        agent_id=agent.id,
        rule="new low confidence",
        source_type="correction",
        confidence=0.1,
        apply_count=3,
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()

    section = _build_behavioral_rules_section(db_session, agent.id, read_only=True)

    db_session.refresh(rule)
    assert rule.is_active is True
    assert "new low confidence" in section


# ---------------------------------------------------------------------------
# Checkpoint pruning (via context assembler)
# ---------------------------------------------------------------------------


def test_checkpoint_pruning_excludes_closed(db_session: Session):
    """Checkpoints for closed conversations should be excluded from context."""
    from backend.openloop.agents.context_assembler import _build_summaries_section

    space = _create_space(db_session)
    agent = _create_agent(db_session)

    # Closed conversation with a checkpoint
    closed_conv = _create_conversation(db_session, space, agent, status="closed")
    db_session.add(
        ConversationSummary(
            conversation_id=closed_conv.id,
            space_id=space.id,
            summary="closed checkpoint summary",
            is_checkpoint=True,
        )
    )

    # Active conversation with a checkpoint
    active_conv = _create_conversation(db_session, space, agent, status="active")
    db_session.add(
        ConversationSummary(
            conversation_id=active_conv.id,
            space_id=space.id,
            summary="active checkpoint summary",
            is_checkpoint=True,
        )
    )

    # Non-checkpoint summary (should always appear)
    db_session.add(
        ConversationSummary(
            conversation_id=closed_conv.id,
            space_id=space.id,
            summary="normal summary",
            is_checkpoint=False,
        )
    )
    db_session.commit()

    section = _build_summaries_section(db_session, space_id=space.id)

    assert "normal summary" in section
    assert "active checkpoint summary" in section
    assert "closed checkpoint summary" not in section
