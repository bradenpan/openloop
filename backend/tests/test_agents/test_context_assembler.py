"""Tests for the Context Assembler module."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from backend.openloop.agents.context_assembler import (
    BUDGET_TODOS_BOARD,
    assemble_context,
    estimate_tokens,
)
from backend.openloop.services import (
    agent_service,
    conversation_service,
    item_service,
    memory_service,
    space_service,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_space(db: Session, name: str = "Test Space", template: str = "project"):
    return space_service.create_space(db, name=name, template=template)


def _make_agent(db: Session, name: str = "TestAgent", **kwargs):
    return agent_service.create_agent(db, name=name, **kwargs)


# ---------------------------------------------------------------------------
# estimate_tokens
# ---------------------------------------------------------------------------


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 100) == 25


# ---------------------------------------------------------------------------
# Space-agent context assembly
# ---------------------------------------------------------------------------


def test_basic_space_assembly(db_session: Session):
    """All sections should be present when data exists in every tier."""
    space = _make_space(db_session)
    agent = _make_agent(
        db_session,
        name="SpaceAgent",
        description="A test agent for the space",
        system_prompt="You help with project management.",
        mcp_tools=["notion", "search"],
    )

    # Create tasks
    item_service.create_item(db_session, space_id=space.id, title="Write docs")
    item_service.create_item(
        db_session,
        space_id=space.id,
        title="Fix bug",
        due_date=datetime.now(UTC) + timedelta(days=2),
    )

    # Create board items
    item_service.create_item(db_session, space_id=space.id, title="Feature A", stage="todo")
    item_service.create_item(db_session, space_id=space.id, title="Feature B", stage="in_progress")

    # Create a conversation with a summary
    conv = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Test conv", space_id=space.id
    )
    conversation_service.add_summary(
        db_session,
        conversation_id=conv.id,
        summary="Discussed project roadmap",
        decisions=["Use FastAPI"],
    )

    # Add memory entries
    memory_service.create_entry(
        db_session,
        namespace=f"space:{space.id}",
        key="tech_stack",
        value="Python + React",
    )
    memory_service.create_entry(
        db_session,
        namespace="global",
        key="timezone",
        value="UTC",
    )

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    # Verify all expected sections are present
    assert "## Agent: SpaceAgent" in result
    assert "A test agent for the space" in result
    assert "You help with project management." in result
    assert "## Current Tasks" in result
    assert "Write docs" in result
    assert "Fix bug" in result
    assert "## Board State" in result
    assert "Feature A" in result
    assert "Feature B" in result
    assert "## Recent Conversations" in result
    assert "Discussed project roadmap" in result
    assert "Decision: Use FastAPI" in result
    assert "## Space Facts" in result
    assert "tech_stack" in result
    assert "## Global Facts" in result
    assert "timezone" in result
    assert "## Available Tools" in result
    assert "notion" in result
    assert "search" in result


def test_empty_space(db_session: Session):
    """An empty space (no todos, items, summaries) should still produce valid context."""
    space = _make_space(db_session, name="Empty Space")
    agent = _make_agent(db_session, name="EmptyAgent", description="Handles empty space")

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    # Agent identity should always be present
    assert "## Agent: EmptyAgent" in result
    assert "Handles empty space" in result

    # None of the data sections should be present
    assert "## Current Tasks" not in result
    assert "## Board State" not in result
    assert "## Recent Conversations" not in result
    assert "## Space Facts" not in result
    assert "## Global Facts" not in result
    assert "## Available Tools" not in result


def test_agent_with_dict_tools(db_session: Session):
    """Agent with structured tool definitions (dict format)."""
    space = _make_space(db_session, name="ToolSpace")
    agent = _make_agent(
        db_session,
        name="ToolAgent",
        mcp_tools=[
            {"name": "create_todo", "description": "Creates a new to-do item"},
            {"name": "search_docs", "description": "Searches documents"},
        ],
    )

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    assert "## Available Tools" in result
    assert "**create_todo**" in result
    assert "Creates a new to-do item" in result
    assert "**search_docs**" in result


# ---------------------------------------------------------------------------
# Odin mode
# ---------------------------------------------------------------------------


def test_odin_mode(db_session: Session):
    """Odin mode (space_id=None) should produce a cross-space overview."""
    space1 = _make_space(db_session, name="Project Alpha", template="project")
    space2 = _make_space(db_session, name="CRM Space", template="crm")

    odin = _make_agent(
        db_session,
        name="Odin",
        description="System-level orchestrator",
        system_prompt="You manage all spaces and agents.",
    )
    helper = _make_agent(db_session, name="Helper", description="Helps with tasks")

    # Link helper to a space
    agent_service.add_agent_to_space(db_session, helper.id, space1.id)

    # Create tasks in different spaces
    item_service.create_item(db_session, space_id=space1.id, title="Alpha task 1")
    item_service.create_item(db_session, space_id=space1.id, title="Alpha task 2")
    item_service.create_item(db_session, space_id=space2.id, title="CRM task")

    # Add global memory
    memory_service.create_entry(db_session, namespace="global", key="owner", value="Brad")

    result = assemble_context(db_session, agent_id=odin.id, space_id=None)

    # Agent identity
    assert "## Agent: Odin" in result
    assert "System-level orchestrator" in result

    # Spaces listing
    assert "## All Spaces" in result
    assert "Project Alpha" in result
    assert "CRM Space" in result

    # Agents listing
    assert "## All Agents" in result
    assert "Odin" in result
    assert "Helper" in result

    # Cross-space task summary
    assert "## Cross-Space Task Summary" in result
    assert "Project Alpha" in result

    # Global facts
    assert "## Global Facts" in result
    assert "owner" in result


# ---------------------------------------------------------------------------
# Token budget enforcement
# ---------------------------------------------------------------------------


def test_task_budget_truncation(db_session: Session):
    """Creating enough tasks to exceed the tier's budget triggers truncation."""
    space = _make_space(db_session, name="Big Space")
    agent = _make_agent(db_session, name="BudgetAgent")

    # Create many tasks with long titles to exceed BUDGET_TODOS_BOARD (1500 tokens = ~6000 chars)
    for i in range(200):
        item_service.create_item(
            db_session,
            space_id=space.id,
            title=f"Task item number {i} with a sufficiently long description to consume tokens",
        )

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    # The task section should exist
    assert "## Current Tasks" in result

    # It should be truncated
    assert "... (truncated)" in result

    # Verify the total task/board section fits within budget
    # Extract the task section
    sections = result.split("\n\n")
    task_section = ""
    for section in sections:
        if "## Current Tasks" in section or "## Board State" in section:
            task_section = section
            break
    # small margin for the truncation marker line
    assert estimate_tokens(task_section) <= BUDGET_TODOS_BOARD + 10


def test_summaries_budget_truncation(db_session: Session):
    """Creating enough summaries to exceed the tier's budget triggers truncation."""
    space = _make_space(db_session, name="Summary Space")
    agent = _make_agent(db_session, name="SummaryAgent")

    conv = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Long conv", space_id=space.id
    )

    # Create many summaries to exceed BUDGET_CONVERSATION_SUMMARIES (2000 tokens = ~8000 chars)
    for i in range(100):
        conversation_service.add_summary(
            db_session,
            conversation_id=conv.id,
            summary=f"Summary {i}: We discussed a very long topic with many details and decisions "
            f"that span multiple words to consume tokens efficiently in this test case.",
            decisions=[f"Decision {i}-a", f"Decision {i}-b"],
        )

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    assert "## Recent Conversations" in result
    assert "... (truncated)" in result


def test_memory_budget_truncation(db_session: Session):
    """Creating enough memory entries to exceed the tier's budget triggers truncation."""
    space = _make_space(db_session, name="Memory Space")
    agent = _make_agent(db_session, name="MemAgent")

    # Create enough entries to exceed BUDGET_SPACE_FACTS (1000 tokens = ~4000 chars)
    for i in range(100):
        memory_service.create_entry(
            db_session,
            namespace=f"space:{space.id}",
            key=f"fact_{i}",
            value=f"This is a fact about topic {i} that is reasonably long to take up space.",
        )

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    assert "## Space Facts" in result
    assert "... (truncated)" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_agent_identity_always_present(db_session: Session):
    """Agent identity section should always appear even with no other data."""
    space = _make_space(db_session, name="Minimal")
    agent = _make_agent(db_session, name="Minimal Agent")

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    # Identity is always the first section (starts the output)
    assert "## Agent: Minimal Agent" in result
    assert result.index("## Agent: Minimal Agent") == 0


def test_odin_empty_system(db_session: Session):
    """Odin mode with no spaces or other data should still work."""
    odin = _make_agent(db_session, name="Odin Solo", description="Alone")

    result = assemble_context(db_session, agent_id=odin.id, space_id=None)

    assert "## Agent: Odin Solo" in result
    assert "Alone" in result


def test_conversation_summaries_with_open_questions(db_session: Session):
    """Summaries with open questions should include them in context."""
    space = _make_space(db_session, name="Q Space")
    agent = _make_agent(db_session, name="QAgent")

    conv = conversation_service.create_conversation(
        db_session, agent_id=agent.id, name="Q conv", space_id=space.id
    )
    conversation_service.add_summary(
        db_session,
        conversation_id=conv.id,
        summary="Discussed API design",
        open_questions=["Should we use REST or GraphQL?"],
    )

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    assert "Open: Should we use REST or GraphQL?" in result


def test_task_with_due_date_display(db_session: Session):
    """Tasks with due dates should show the date in context."""
    space = _make_space(db_session, name="Due Space")
    agent = _make_agent(db_session, name="DueAgent")

    item_service.create_item(
        db_session,
        space_id=space.id,
        title="Urgent task",
        due_date=datetime(2026, 4, 15, tzinfo=UTC),
    )

    result = assemble_context(db_session, agent_id=agent.id, space_id=space.id)

    assert "Urgent task" in result
    assert "2026-04-15" in result


def test_odin_overdue_tasks(db_session: Session):
    """Odin should see overdue tasks in the attention summary."""
    space = _make_space(db_session, name="Overdue Space")
    odin = _make_agent(db_session, name="Odin Overdue")

    # Create an overdue task
    item_service.create_item(
        db_session,
        space_id=space.id,
        title="Overdue task",
        due_date=datetime(2020, 1, 1, tzinfo=UTC),
    )

    result = assemble_context(db_session, agent_id=odin.id, space_id=None)

    assert "## Cross-Space Task Summary" in result
    assert "Overdue Space" in result
    assert "Overdue" in result
    assert "Overdue task" in result
