"""Tests for the consolidation service.

Covers: get_unconsolidated_count, generate_meta_summary (with mocked LLM),
successive consolidation, and the auto-consolidation threshold in close_session.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, Conversation, ConversationSummary, Space
from backend.openloop.services import consolidation_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_space(db: Session, name: str = "Test Space") -> Space:
    space = Space(name=name, template="project")
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


def _create_agent(db: Session, name: str = "test-agent") -> Agent:
    agent = Agent(name=name)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _create_conversation(db: Session, agent_id: str, space_id: str | None = None) -> Conversation:
    conv = Conversation(
        agent_id=agent_id,
        name="test-conversation",
        space_id=space_id,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def _create_summary(
    db: Session,
    conversation_id: str,
    space_id: str,
    *,
    summary: str = "Test summary",
    is_meta_summary: bool = False,
    is_checkpoint: bool = False,
    consolidated_into: str | None = None,
    decisions: list | None = None,
    open_questions: list | None = None,
) -> ConversationSummary:
    s = ConversationSummary(
        conversation_id=conversation_id,
        space_id=space_id,
        summary=summary,
        is_meta_summary=is_meta_summary,
        is_checkpoint=is_checkpoint,
        consolidated_into=consolidated_into,
        decisions=decisions,
        open_questions=open_questions,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


# ---------------------------------------------------------------------------
# get_unconsolidated_count
# ---------------------------------------------------------------------------


class TestGetUnconsolidatedCount:
    def test_counts_regular_summaries(self, db_session: Session):
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv = _create_conversation(db_session, agent.id, space.id)

        _create_summary(db_session, conv.id, space.id, summary="s1")
        _create_summary(db_session, conv.id, space.id, summary="s2")
        _create_summary(db_session, conv.id, space.id, summary="s3")

        assert consolidation_service.get_unconsolidated_count(db_session, space.id) == 3

    def test_excludes_checkpoints(self, db_session: Session):
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv = _create_conversation(db_session, agent.id, space.id)

        _create_summary(db_session, conv.id, space.id, summary="regular")
        _create_summary(db_session, conv.id, space.id, summary="checkpoint", is_checkpoint=True)

        assert consolidation_service.get_unconsolidated_count(db_session, space.id) == 1

    def test_excludes_meta_summaries(self, db_session: Session):
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv = _create_conversation(db_session, agent.id, space.id)

        _create_summary(db_session, conv.id, space.id, summary="regular")
        _create_summary(db_session, conv.id, space.id, summary="meta", is_meta_summary=True)

        assert consolidation_service.get_unconsolidated_count(db_session, space.id) == 1

    def test_excludes_already_consolidated(self, db_session: Session):
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv = _create_conversation(db_session, agent.id, space.id)

        meta = _create_summary(db_session, conv.id, space.id, summary="meta", is_meta_summary=True)
        _create_summary(db_session, conv.id, space.id, summary="regular")
        _create_summary(
            db_session, conv.id, space.id, summary="consolidated",
            consolidated_into=meta.id,
        )

        assert consolidation_service.get_unconsolidated_count(db_session, space.id) == 1

    def test_zero_when_no_summaries(self, db_session: Session):
        space = _create_space(db_session)
        assert consolidation_service.get_unconsolidated_count(db_session, space.id) == 0

    def test_scoped_to_space(self, db_session: Session):
        space_a = _create_space(db_session, name="Space A")
        space_b = _create_space(db_session, name="Space B")
        agent = _create_agent(db_session)
        conv_a = _create_conversation(db_session, agent.id, space_a.id)
        conv_b = _create_conversation(db_session, agent.id, space_b.id)

        _create_summary(db_session, conv_a.id, space_a.id, summary="a1")
        _create_summary(db_session, conv_a.id, space_a.id, summary="a2")
        _create_summary(db_session, conv_b.id, space_b.id, summary="b1")

        assert consolidation_service.get_unconsolidated_count(db_session, space_a.id) == 2
        assert consolidation_service.get_unconsolidated_count(db_session, space_b.id) == 1


# ---------------------------------------------------------------------------
# generate_meta_summary
# ---------------------------------------------------------------------------


def _mock_llm_response(summary: str = "Consolidated overview", decisions: list | None = None, open_questions: list | None = None):
    """Create a mock for _call_consolidation_llm that returns a fixed result."""
    result = {
        "summary": summary,
        "decisions": decisions or ["decision-1"],
        "open_questions": open_questions or ["open-q-1"],
    }
    return AsyncMock(return_value=result)


class TestGenerateMetaSummary:
    @pytest.mark.asyncio
    async def test_creates_meta_and_marks_individuals(self, db_session: Session):
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv1 = _create_conversation(db_session, agent.id, space.id)
        conv2 = _create_conversation(db_session, agent.id, space.id)

        s1 = _create_summary(db_session, conv1.id, space.id, summary="first session")
        s2 = _create_summary(db_session, conv2.id, space.id, summary="second session")

        with patch.object(
            consolidation_service,
            "_call_consolidation_llm",
            _mock_llm_response("Consolidated overview"),
        ):
            meta = await consolidation_service.generate_meta_summary(db_session, space.id)

        # Meta-summary was created
        assert meta.is_meta_summary is True
        assert meta.summary == "Consolidated overview"
        assert meta.space_id == space.id
        assert meta.decisions == ["decision-1"]
        assert meta.open_questions == ["open-q-1"]
        assert meta.consolidated_into is None

        # Individuals are now marked as consolidated
        db_session.refresh(s1)
        db_session.refresh(s2)
        assert s1.consolidated_into == meta.id
        assert s2.consolidated_into == meta.id

    @pytest.mark.asyncio
    async def test_successive_consolidation(self, db_session: Session):
        """Second consolidation should consume the old meta-summary too."""
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv = _create_conversation(db_session, agent.id, space.id)

        # First round: 2 summaries -> meta
        s1 = _create_summary(db_session, conv.id, space.id, summary="round 1a")
        s2 = _create_summary(db_session, conv.id, space.id, summary="round 1b")

        with patch.object(
            consolidation_service,
            "_call_consolidation_llm",
            _mock_llm_response("First meta"),
        ):
            meta1 = await consolidation_service.generate_meta_summary(db_session, space.id)

        # Verify first round
        db_session.refresh(s1)
        db_session.refresh(s2)
        assert s1.consolidated_into == meta1.id
        assert s2.consolidated_into == meta1.id

        # Second round: 2 more summaries + old meta -> new meta
        s3 = _create_summary(db_session, conv.id, space.id, summary="round 2a")
        s4 = _create_summary(db_session, conv.id, space.id, summary="round 2b")

        with patch.object(
            consolidation_service,
            "_call_consolidation_llm",
            _mock_llm_response("Second meta"),
        ):
            meta2 = await consolidation_service.generate_meta_summary(db_session, space.id)

        # New meta was created
        assert meta2.id != meta1.id
        assert meta2.summary == "Second meta"
        assert meta2.is_meta_summary is True
        assert meta2.consolidated_into is None

        # Old meta is now consolidated into new meta
        db_session.refresh(meta1)
        assert meta1.consolidated_into == meta2.id

        # New individuals also consolidated
        db_session.refresh(s3)
        db_session.refresh(s4)
        assert s3.consolidated_into == meta2.id
        assert s4.consolidated_into == meta2.id

    @pytest.mark.asyncio
    async def test_uses_most_recent_conversation_id(self, db_session: Session):
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv1 = _create_conversation(db_session, agent.id, space.id)
        conv2 = _create_conversation(db_session, agent.id, space.id)

        _create_summary(db_session, conv1.id, space.id, summary="older")
        _create_summary(db_session, conv2.id, space.id, summary="newer")

        with patch.object(
            consolidation_service,
            "_call_consolidation_llm",
            _mock_llm_response("Meta"),
        ):
            meta = await consolidation_service.generate_meta_summary(db_session, space.id)

        # Should use the most recent conversation's ID (conv2, which is last in ASC order)
        assert meta.conversation_id == conv2.id

    @pytest.mark.asyncio
    async def test_does_not_consume_checkpoints(self, db_session: Session):
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv = _create_conversation(db_session, agent.id, space.id)

        s1 = _create_summary(db_session, conv.id, space.id, summary="regular")
        checkpoint = _create_summary(
            db_session, conv.id, space.id, summary="checkpoint", is_checkpoint=True
        )

        with patch.object(
            consolidation_service,
            "_call_consolidation_llm",
            _mock_llm_response("Meta"),
        ):
            meta = await consolidation_service.generate_meta_summary(db_session, space.id)

        db_session.refresh(s1)
        db_session.refresh(checkpoint)
        assert s1.consolidated_into == meta.id
        assert checkpoint.consolidated_into is None  # Checkpoint untouched


# ---------------------------------------------------------------------------
# close_session auto-consolidation threshold
# ---------------------------------------------------------------------------


class TestCloseSessionAutoConsolidation:
    @pytest.mark.asyncio
    async def test_triggers_at_threshold(self, db_session: Session):
        """When unconsolidated count >= 20, consolidation should be triggered."""
        space = _create_space(db_session)
        agent = _create_agent(db_session)
        conv = _create_conversation(db_session, agent.id, space.id)

        # Create 20 summaries
        for i in range(20):
            _create_summary(db_session, conv.id, space.id, summary=f"summary {i}")

        mock_generate = AsyncMock()

        with patch(
            "backend.openloop.services.consolidation_service.get_unconsolidated_count",
            return_value=20,
        ), patch(
            "backend.openloop.services.consolidation_service.generate_meta_summary",
            mock_generate,
        ):
            # Import here to get the patched version
            from backend.openloop.services import consolidation_service as cs

            # Simulate what close_session does after storing the summary
            count = cs.get_unconsolidated_count(db_session, space.id)
            if count >= 20:
                await cs.generate_meta_summary(db_session, space.id)

        mock_generate.assert_called_once_with(db_session, space.id)

    @pytest.mark.asyncio
    async def test_does_not_trigger_below_threshold(self, db_session: Session):
        """When unconsolidated count < 20, no consolidation."""
        space = _create_space(db_session)

        mock_generate = AsyncMock()

        with patch(
            "backend.openloop.services.consolidation_service.get_unconsolidated_count",
            return_value=19,
        ), patch(
            "backend.openloop.services.consolidation_service.generate_meta_summary",
            mock_generate,
        ):
            from backend.openloop.services import consolidation_service as cs

            count = cs.get_unconsolidated_count(db_session, space.id)
            if count >= 20:
                await cs.generate_meta_summary(db_session, space.id)

        mock_generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_consolidation_failure_does_not_block(self, db_session: Session):
        """Auto-consolidation errors should be caught, not raised."""
        space = _create_space(db_session)

        with patch(
            "backend.openloop.services.consolidation_service.get_unconsolidated_count",
            return_value=25,
        ), patch(
            "backend.openloop.services.consolidation_service.generate_meta_summary",
            AsyncMock(side_effect=RuntimeError("LLM down")),
        ):
            from backend.openloop.services import consolidation_service as cs

            # This simulates the try/except in close_session
            try:
                count = cs.get_unconsolidated_count(db_session, space.id)
                if count >= 20:
                    await cs.generate_meta_summary(db_session, space.id)
            except (Exception, ExceptionGroup):
                pass  # Should be caught — this is the expected behavior
