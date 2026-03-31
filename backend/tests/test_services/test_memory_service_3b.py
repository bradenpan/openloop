"""Tests for Phase 3b memory service additions.

Covers: _compute_score, _get_namespace_cap, get_scored_entries, archive_entry,
save_fact_with_dedup (mocked LLM), temporal facts, and cap enforcement.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.services import memory_service
from contract.enums import DedupDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_entry(db: Session, namespace: str, key: str, value: str, **kwargs):
    """Shorthand for creating a memory entry."""
    return memory_service.create_entry(
        db, namespace=namespace, key=key, value=value, **kwargs
    )


# ---------------------------------------------------------------------------
# _get_namespace_cap
# ---------------------------------------------------------------------------


class TestGetNamespaceCap:
    def test_global_cap(self):
        assert memory_service._get_namespace_cap("global") == 50

    def test_odin_cap(self):
        assert memory_service._get_namespace_cap("odin") == 50

    def test_space_prefix_cap(self):
        assert memory_service._get_namespace_cap("space:abc-123") == 50

    def test_agent_prefix_cap(self):
        assert memory_service._get_namespace_cap("agent:helper") == 20

    def test_unknown_namespace_fallback(self):
        assert memory_service._get_namespace_cap("custom:whatever") == 50


# ---------------------------------------------------------------------------
# _compute_score
# ---------------------------------------------------------------------------


class TestComputeScore:
    def test_high_importance_high_access(self, db_session: Session):
        entry = _create_entry(db_session, "global", "high-high", "important and frequent")
        entry.importance = 1.0
        entry.access_count = 10
        db_session.commit()
        db_session.refresh(entry)
        score = memory_service._compute_score(entry)
        assert score > 0

    def test_low_importance_low_access(self, db_session: Session):
        entry = _create_entry(db_session, "global", "low-low", "unimportant and rare")
        entry.importance = 0.1
        entry.access_count = 0
        db_session.commit()
        db_session.refresh(entry)
        score = memory_service._compute_score(entry)
        assert score > 0

    def test_high_beats_low(self, db_session: Session):
        high = _create_entry(db_session, "global", "high", "important")
        high.importance = 1.0
        high.access_count = 10
        db_session.commit()
        db_session.refresh(high)

        low = _create_entry(db_session, "global", "low", "not important")
        low.importance = 0.1
        low.access_count = 0
        db_session.commit()
        db_session.refresh(low)

        assert memory_service._compute_score(high) > memory_service._compute_score(low)

    def test_old_low_importance_scores_lower(self, db_session: Session):
        """Old entries with low importance should decay faster."""
        recent = _create_entry(db_session, "global", "recent", "just created")
        recent.importance = 0.3
        db_session.commit()
        db_session.refresh(recent)

        old = _create_entry(db_session, "global", "old", "created a while ago")
        old.importance = 0.3
        old.created_at = datetime.now(UTC) - timedelta(days=30)
        # last_accessed is None so it falls back to created_at
        old.last_accessed = None
        db_session.commit()
        db_session.refresh(old)

        assert memory_service._compute_score(recent) > memory_service._compute_score(old)


# ---------------------------------------------------------------------------
# get_scored_entries
# ---------------------------------------------------------------------------


class TestGetScoredEntries:
    def test_returns_in_score_order(self, db_session: Session):
        """Entries should be returned in descending score order."""
        e_low = _create_entry(db_session, "space:test", "low", "low importance")
        e_low.importance = 0.1
        db_session.commit()

        e_high = _create_entry(db_session, "space:test", "high", "high importance")
        e_high.importance = 1.0
        e_high.access_count = 5
        db_session.commit()

        results = memory_service.get_scored_entries(db_session, "space:test")
        assert len(results) == 2
        assert results[0].key == "high"
        assert results[1].key == "low"

    def test_access_count_incremented(self, db_session: Session):
        """Retrieval should increment access_count."""
        entry = _create_entry(db_session, "space:test", "tracked", "value")
        assert entry.access_count == 0

        memory_service.get_scored_entries(db_session, "space:test")
        db_session.refresh(entry)
        assert entry.access_count == 1

        memory_service.get_scored_entries(db_session, "space:test")
        db_session.refresh(entry)
        assert entry.access_count == 2

    def test_last_accessed_updated(self, db_session: Session):
        """Retrieval should set last_accessed."""
        entry = _create_entry(db_session, "space:test", "accessed", "value")
        assert entry.last_accessed is None

        memory_service.get_scored_entries(db_session, "space:test")
        db_session.refresh(entry)
        assert entry.last_accessed is not None

    def test_limit_parameter(self, db_session: Session):
        for i in range(5):
            _create_entry(db_session, "space:limit", f"key-{i}", f"value-{i}")

        results = memory_service.get_scored_entries(db_session, "space:limit", limit=3)
        assert len(results) == 3

    def test_excludes_archived_by_default(self, db_session: Session):
        active = _create_entry(db_session, "space:arc", "active", "still here")
        archived = _create_entry(db_session, "space:arc", "archived", "gone")
        memory_service.archive_entry(db_session, archived.id)

        results = memory_service.get_scored_entries(db_session, "space:arc")
        assert len(results) == 1
        assert results[0].key == "active"


# ---------------------------------------------------------------------------
# archive_entry
# ---------------------------------------------------------------------------


class TestArchiveEntry:
    def test_archive_sets_archived_at(self, db_session: Session):
        entry = _create_entry(db_session, "global", "to-archive", "value")
        assert entry.archived_at is None

        archived = memory_service.archive_entry(db_session, entry.id)
        assert archived.archived_at is not None

    def test_archived_excluded_from_list_entries(self, db_session: Session):
        entry = _create_entry(db_session, "global", "hide-me", "value")
        memory_service.archive_entry(db_session, entry.id)

        entries = memory_service.list_entries(db_session, namespace="global")
        assert len(entries) == 0

    def test_archived_included_with_flag(self, db_session: Session):
        entry = _create_entry(db_session, "global", "show-me", "value")
        memory_service.archive_entry(db_session, entry.id)

        entries = memory_service.list_entries(
            db_session, namespace="global", include_archived=True
        )
        assert len(entries) == 1
        assert entries[0].key == "show-me"


# ---------------------------------------------------------------------------
# save_fact_with_dedup (mocked LLM)
# ---------------------------------------------------------------------------


class TestSaveFactWithDedup:
    @pytest.mark.asyncio
    async def test_add_decision_creates_new_entry(self, db_session: Session):
        """When LLM says ADD, a new entry should be created."""
        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "add",
                "target_id": None,
                "merged_content": None,
            }
            decision, entry = await memory_service.save_fact_with_dedup(
                db_session, namespace="space:test", content="Brand new fact"
            )

        assert decision == DedupDecision.ADD
        assert entry.value == "Brand new fact"
        assert entry.namespace == "space:test"
        assert entry.id is not None

    @pytest.mark.asyncio
    async def test_update_decision_merges_content(self, db_session: Session):
        """When LLM says UPDATE with target_id, existing entry should be updated."""
        existing = _create_entry(db_session, "space:test", "old-fact", "old value")

        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "update",
                "target_id": existing.id,
                "merged_content": "old value plus new info",
            }
            decision, entry = await memory_service.save_fact_with_dedup(
                db_session, namespace="space:test", content="new info"
            )

        assert decision == DedupDecision.UPDATE
        assert entry.id == existing.id
        assert entry.value == "old value plus new info"

    @pytest.mark.asyncio
    async def test_delete_decision_supersedes(self, db_session: Session):
        """When LLM says DELETE, old entry gets valid_until, new entry created."""
        old = _create_entry(db_session, "space:test", "stale-fact", "stale value")

        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "delete",
                "target_id": old.id,
                "merged_content": None,
            }
            decision, entry = await memory_service.save_fact_with_dedup(
                db_session, namespace="space:test", content="replacement fact"
            )

        assert decision == DedupDecision.DELETE
        assert entry.id != old.id
        assert entry.value == "replacement fact"

        # Old entry should have valid_until set
        db_session.refresh(old)
        assert old.valid_until is not None

    @pytest.mark.asyncio
    async def test_noop_decision_returns_existing(self, db_session: Session):
        """When LLM says NOOP with target_id, return existing entry without creating."""
        existing = _create_entry(db_session, "space:test", "dup", "already there")

        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "noop",
                "target_id": existing.id,
                "merged_content": None,
            }
            decision, entry = await memory_service.save_fact_with_dedup(
                db_session, namespace="space:test", content="same info"
            )

        assert decision == DedupDecision.NOOP
        assert entry.id == existing.id

    @pytest.mark.asyncio
    async def test_add_at_cap_archives_lowest(self, db_session: Session):
        """Adding at namespace cap should archive the lowest-scored entry."""
        # agent: namespace has cap of 20
        ns = "agent:test-cap"
        entries = []
        for i in range(20):
            e = _create_entry(db_session, ns, f"key-{i}", f"value-{i}")
            e.importance = 0.5
            entries.append(e)
        # Make one entry very low-scored
        entries[0].importance = 0.01
        entries[0].access_count = 0
        db_session.commit()

        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "add",
                "target_id": None,
                "merged_content": None,
            }
            decision, new_entry = await memory_service.save_fact_with_dedup(
                db_session, namespace=ns, content="entry 21"
            )

        assert decision == DedupDecision.ADD
        # The lowest scored entry should be archived
        db_session.refresh(entries[0])
        assert entries[0].archived_at is not None

        # Total active entries should still be at cap (20: 19 original + 1 new)
        active = memory_service.list_entries(db_session, namespace=ns)
        assert len(active) == 20


# ---------------------------------------------------------------------------
# Temporal facts
# ---------------------------------------------------------------------------


class TestTemporalFacts:
    @pytest.mark.asyncio
    async def test_superseded_fact_has_valid_until(self, db_session: Session):
        """When a fact is superseded (DELETE decision), old one gets valid_until."""
        old = _create_entry(db_session, "space:temporal", "owner", "Alice owns the budget")

        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "delete",
                "target_id": old.id,
                "merged_content": None,
            }
            _, new = await memory_service.save_fact_with_dedup(
                db_session,
                namespace="space:temporal",
                content="Bob now owns the budget",
            )

        db_session.refresh(old)
        assert old.valid_until is not None
        assert new.valid_from is not None

    @pytest.mark.asyncio
    async def test_superseded_entry_has_valid_until_while_new_does_not(self, db_session: Session):
        """After supersession, old entry has valid_until set, new entry does not."""
        old = _create_entry(db_session, "space:temporal", "data", "outdated")

        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "delete",
                "target_id": old.id,
                "merged_content": None,
            }
            _, new = await memory_service.save_fact_with_dedup(
                db_session, namespace="space:temporal", content="current"
            )

        db_session.refresh(old)
        assert old.valid_until is not None
        assert new.valid_until is None

        # Scored entries excludes superseded (valid_until set) — only current fact returned
        results = memory_service.get_scored_entries(db_session, "space:temporal")
        assert len(results) == 1
        assert results[0].value == "current"


# ---------------------------------------------------------------------------
# Cap enforcement
# ---------------------------------------------------------------------------


class TestCapEnforcement:
    @pytest.mark.asyncio
    async def test_stays_at_cap_after_addition(self, db_session: Session):
        """Filling a namespace to cap and adding one more keeps active count at cap."""
        ns = "space:cap-test"
        cap = memory_service._get_namespace_cap(ns)  # 50

        for i in range(cap):
            e = _create_entry(db_session, ns, f"fact-{i}", f"value-{i}")
            e.importance = 0.5
            db_session.commit()

        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "add",
                "target_id": None,
                "merged_content": None,
            }
            await memory_service.save_fact_with_dedup(
                db_session, namespace=ns, content="one more"
            )

        active = memory_service.list_entries(db_session, namespace=ns)
        assert len(active) == cap

    @pytest.mark.asyncio
    async def test_lowest_scored_archived(self, db_session: Session):
        """The lowest-scored entry should be the one archived when at cap."""
        ns = "agent:cap-low"
        cap = memory_service._get_namespace_cap(ns)  # 20

        entries = []
        for i in range(cap):
            e = _create_entry(db_session, ns, f"k-{i}", f"v-{i}")
            e.importance = 0.5 + (i * 0.02)  # gradually increasing importance
            entries.append(e)
        # First entry has lowest importance
        entries[0].importance = 0.01
        db_session.commit()

        with patch(
            "backend.openloop.services.llm_utils.llm_compare_facts",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = {
                "decision": "add",
                "target_id": None,
                "merged_content": None,
            }
            await memory_service.save_fact_with_dedup(
                db_session, namespace=ns, content="overflow"
            )

        db_session.refresh(entries[0])
        assert entries[0].archived_at is not None
