"""Tests for Phase 3b context assembler changes.

Covers: attention-optimized ordering, behavioral rules injection, scored
retrieval, meta-summary handling, and memory management instructions.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from backend.openloop.agents.context_assembler import assemble_context
from backend.openloop.db.models import ConversationSummary
from backend.openloop.services import (
    agent_service,
    behavioral_rule_service,
    conversation_service,
    memory_service,
    space_service,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_space(db: Session, name: str = "Test Space"):
    return space_service.create_space(db, name=name, template="project")


def _make_agent(db: Session, name: str = "TestAgent", **kwargs):
    return agent_service.create_agent(db, name=name, **kwargs)


def _make_conversation(db: Session, agent_id: str, space_id: str, **kwargs):
    return conversation_service.create_conversation(
        db, agent_id=agent_id, name="Test Conv", space_id=space_id, **kwargs
    )


# ---------------------------------------------------------------------------
# Ordering tests
# ---------------------------------------------------------------------------


class TestAttentionOptimizedOrdering:
    def test_section_ordering(self, db_session: Session):
        """Sections should follow the attention-optimized order:
        BEGINNING: Agent identity > Confirmed rules > Tool docs
        MIDDLE: Inferred rules > Summaries > Space facts > Global facts
        END: Todos/Board state

        Task 8.3: Rules are now split by origin — user_confirmed/system rules
        go in BEGINNING, agent_inferred rules go in MIDDLE.
        """
        space = _make_space(db_session)
        agent = _make_agent(
            db_session,
            name="OrderAgent",
            description="Tests ordering",
            system_prompt="You test ordering.",
            mcp_tools=["search"],
        )

        # Create a user-confirmed rule (BEGINNING section)
        behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Always be concise",
            origin="user_confirmed",
        )
        # Create an agent-inferred rule (MIDDLE section)
        behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Use markdown formatting",
            origin="agent_inferred",
        )

        # Create conversation with summary
        conv = _make_conversation(db_session, agent.id, space.id)
        conversation_service.add_summary(
            db_session, conversation_id=conv.id, summary="Discussed ordering"
        )

        # Create memory entries
        memory_service.create_entry(
            db_session, namespace=f"space:{space.id}", key="space-fact", value="space value"
        )
        memory_service.create_entry(
            db_session, namespace="global", key="global-fact", value="global value"
        )

        # Create a task (goes in END section)
        from backend.openloop.services import item_service

        item_service.create_item(db_session, space_id=space.id, title="Test task")

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        # Verify ordering:
        # BEGINNING: Agent identity < Confirmed Rules < Tools
        # MIDDLE: Inferred Rules < Summaries < Space facts < Global facts
        # END: Todos
        agent_pos = result.index("## Agent: OrderAgent")
        confirmed_rules_pos = result.index("## Behavioral Rules (Confirmed)")
        tools_pos = result.index("## Available Tools")
        inferred_rules_pos = result.index("## Behavioral Rules (Inferred)")
        summary_pos = result.index("## Recent Conversations")
        space_facts_pos = result.index("## Space Facts")
        global_facts_pos = result.index("## Global Facts")
        todo_pos = result.index("## Current Tasks")

        assert agent_pos < confirmed_rules_pos < tools_pos
        assert tools_pos < inferred_rules_pos < summary_pos
        assert summary_pos < space_facts_pos < global_facts_pos
        assert global_facts_pos < todo_pos


# ---------------------------------------------------------------------------
# Behavioral rules injection
# ---------------------------------------------------------------------------


class TestBehavioralRulesInjection:
    def test_rules_appear_in_context(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="RuleAgent")

        behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Always use bullet points"
        )
        behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Never use emojis"
        )

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        assert "## Behavioral Rules" in result
        assert "Always use bullet points" in result
        assert "Never use emojis" in result

    def test_confidence_scores_shown(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="ConfAgent")

        rule = behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Be formal"
        )
        # Confirm a few times to raise confidence
        for _ in range(3):
            behavioral_rule_service.confirm_rule(db_session, rule.id)
        db_session.refresh(rule)

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        assert f"[confidence: {rule.confidence}]" in result

    def test_apply_count_incremented(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="ApplyAgent")

        rule = behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Test rule"
        )
        assert rule.apply_count == 0

        assemble_context(db_session, agent_id=agent.id, space_id=space.id)
        db_session.refresh(rule)
        assert rule.apply_count == 1

    def test_no_rules_section_when_empty(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="NoRulesAgent")

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)
        assert "## Behavioral Rules" not in result

    def test_inactive_rules_excluded(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="InactiveAgent")

        behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Active rule"
        )
        inactive = behavioral_rule_service.create_rule(
            db_session, agent_id=agent.id, rule="Inactive rule"
        )
        behavioral_rule_service.deactivate_rule(db_session, inactive.id)

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        assert "Active rule" in result
        assert "Inactive rule" not in result


# ---------------------------------------------------------------------------
# Scored retrieval
# ---------------------------------------------------------------------------


class TestScoredRetrieval:
    def test_higher_scored_entries_appear_first(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="ScoreAgent")

        low = memory_service.create_entry(
            db_session,
            namespace=f"space:{space.id}",
            key="low-priority",
            value="low priority value",
        )
        low.importance = 0.1
        db_session.commit()

        high = memory_service.create_entry(
            db_session,
            namespace=f"space:{space.id}",
            key="high-priority",
            value="high priority value",
        )
        high.importance = 1.0
        high.access_count = 5
        db_session.commit()

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        # high-priority should appear before low-priority in the Space Facts section
        high_pos = result.index("high-priority")
        low_pos = result.index("low-priority")
        assert high_pos < low_pos

    def test_access_count_incremented_by_assembly(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="AccessAgent")

        entry = memory_service.create_entry(
            db_session,
            namespace=f"space:{space.id}",
            key="tracked",
            value="tracked value",
        )
        assert entry.access_count == 0

        assemble_context(db_session, agent_id=agent.id, space_id=space.id)
        db_session.refresh(entry)
        assert entry.access_count >= 1


# ---------------------------------------------------------------------------
# Meta-summary handling
# ---------------------------------------------------------------------------


class TestMetaSummaryHandling:
    def test_meta_summary_appears_as_project_overview(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="MetaAgent")

        conv = _make_conversation(db_session, agent.id, space.id)

        # Create a meta-summary directly via the ORM
        meta = ConversationSummary(
            conversation_id=conv.id,
            space_id=space.id,
            summary="This project builds an AI command center.",
            is_meta_summary=True,
            decisions=["Use FastAPI + React"],
        )
        db_session.add(meta)
        db_session.commit()

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        assert "## Project Overview" in result
        assert "This project builds an AI command center." in result
        assert "Decision: Use FastAPI + React" in result

    def test_individual_summaries_under_recent_conversations(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="IndivAgent")

        conv = _make_conversation(db_session, agent.id, space.id)
        conversation_service.add_summary(
            db_session, conversation_id=conv.id, summary="Discussed API design"
        )

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)
        assert "## Recent Conversations" in result
        assert "Discussed API design" in result

    def test_consolidated_summaries_excluded(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="ConsolidAgent")

        conv = _make_conversation(db_session, agent.id, space.id)

        # Create a meta-summary
        meta = ConversationSummary(
            conversation_id=conv.id,
            space_id=space.id,
            summary="Meta overview",
            is_meta_summary=True,
        )
        db_session.add(meta)
        db_session.commit()
        db_session.refresh(meta)

        # Create an individual summary that has been consolidated
        consolidated = ConversationSummary(
            conversation_id=conv.id,
            space_id=space.id,
            summary="This was consolidated and should not appear",
            is_meta_summary=False,
            consolidated_into=meta.id,
        )
        db_session.add(consolidated)
        db_session.commit()

        # Create an unconsolidated summary that should appear
        unconsolidated = ConversationSummary(
            conversation_id=conv.id,
            space_id=space.id,
            summary="This is fresh and should appear",
            is_meta_summary=False,
        )
        db_session.add(unconsolidated)
        db_session.commit()

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        assert "Meta overview" in result
        assert "This was consolidated and should not appear" not in result
        assert "This is fresh and should appear" in result

    def test_meta_and_individual_both_present(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="BothAgent")

        conv = _make_conversation(db_session, agent.id, space.id)

        meta = ConversationSummary(
            conversation_id=conv.id,
            space_id=space.id,
            summary="Project-level overview",
            is_meta_summary=True,
        )
        db_session.add(meta)
        db_session.commit()

        individual = ConversationSummary(
            conversation_id=conv.id,
            space_id=space.id,
            summary="Recent discussion about testing",
            is_meta_summary=False,
        )
        db_session.add(individual)
        db_session.commit()

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        assert "## Project Overview" in result
        assert "## Recent Conversations" in result
        overview_pos = result.index("## Project Overview")
        recent_pos = result.index("## Recent Conversations")
        assert overview_pos < recent_pos


# ---------------------------------------------------------------------------
# Memory management instructions
# ---------------------------------------------------------------------------


class TestMemoryManagementInstructions:
    def test_instructions_present(self, db_session: Session):
        space = _make_space(db_session)
        agent = _make_agent(db_session, name="MemInstrAgent")

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        assert "## Memory Management Instructions" in result
        assert "save_fact()" in result
        assert "save_rule()" in result
        assert "confirm_rule()" in result
        assert "override_rule()" in result

    def test_instructions_within_agent_identity(self, db_session: Session):
        """Memory instructions should be within the agent identity section (beginning)."""
        space = _make_space(db_session)
        agent = _make_agent(
            db_session, name="InstrPosAgent", mcp_tools=["search"]
        )

        result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

        # Memory instructions should come before tool docs
        mem_pos = result.index("## Memory Management Instructions")
        tool_pos = result.index("## Available Tools")
        assert mem_pos < tool_pos

    def test_instructions_present_for_odin(self, db_session: Session):
        """Odin should also get memory management instructions."""
        agent = _make_agent(db_session, name="OdinInstr", description="Orchestrator")

        result = assemble_context(db_session, agent_id=agent.id, space_id=None)
        assert "## Memory Management Instructions" in result
