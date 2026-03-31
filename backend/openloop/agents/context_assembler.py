"""Context Assembler — builds the system prompt for agent sessions.

Pulls from multiple data tiers (agent identity, todos, board items,
conversation summaries, memory, tool docs) and manages a token budget
so context doesn't overwhelm the conversation.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, Item, Todo
from backend.openloop.services import (
    agent_service,
    conversation_service,
    item_service,
    memory_service,
    space_service,
    todo_service,
)

# ---------------------------------------------------------------------------
# Token budgets (approximate, using 1 token ≈ 4 chars heuristic)
# ---------------------------------------------------------------------------

BUDGET_AGENT_IDENTITY = 2000
BUDGET_TODOS_BOARD = 1500
BUDGET_CONVERSATION_SUMMARIES = 2000
BUDGET_SPACE_FACTS = 1000
BUDGET_GLOBAL_FACTS = 500
BUDGET_TOOL_DOCS = 1000

# Odin mode uses a lighter total budget
BUDGET_ODIN_TOTAL = 4000


def estimate_tokens(text: str) -> int:
    """Estimate token count using a character-based heuristic (1 token ≈ 4 chars)."""
    return len(text) // 4


def _naive_utc(dt: datetime) -> datetime:
    """Strip timezone info for safe comparison (SQLite stores naive datetimes)."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assemble_context(
    db: Session,
    *,
    agent_id: str,
    space_id: str | None = None,
    conversation_id: str | None = None,
) -> str:
    """Assemble the system prompt context for an agent session.

    For space agents (space_id provided), assembles six tiers in priority order.
    For Odin (space_id is None), assembles a cross-space overview.
    """
    agent = agent_service.get_agent(db, agent_id)

    if space_id is None:
        return _assemble_odin_context(db, agent)
    return _assemble_space_context(db, agent, space_id, conversation_id)


# ---------------------------------------------------------------------------
# Space-agent assembly
# ---------------------------------------------------------------------------


def _assemble_space_context(
    db: Session,
    agent: Agent,
    space_id: str,
    conversation_id: str | None,
) -> str:
    """Assemble context for an agent operating within a specific space."""
    sections: list[str] = []

    # 1. Agent identity + role prompt (always included, up to budget)
    identity = _build_agent_identity(agent)
    sections.append(_truncate_to_budget(identity, BUDGET_AGENT_IDENTITY))

    # 2. To-do + board state
    todo_board = _build_todo_board_section(db, space_id)
    if todo_board:
        sections.append(_truncate_to_budget(todo_board, BUDGET_TODOS_BOARD))

    # 3. Conversation summaries (recent first)
    summaries = _build_summaries_section(db, space_id=space_id)
    if summaries:
        sections.append(_truncate_to_budget(summaries, BUDGET_CONVERSATION_SUMMARIES))

    # 4. Space facts (memory)
    space_facts = _build_memory_section(db, namespace=f"space:{space_id}", header="Space Facts")
    if space_facts:
        sections.append(_truncate_to_budget(space_facts, BUDGET_SPACE_FACTS))

    # 5. Global facts (memory)
    global_facts = _build_memory_section(db, namespace="global", header="Global Facts")
    if global_facts:
        sections.append(_truncate_to_budget(global_facts, BUDGET_GLOBAL_FACTS))

    # 6. Available tools documentation
    tool_docs = _build_tool_docs_section(agent)
    if tool_docs:
        sections.append(_truncate_to_budget(tool_docs, BUDGET_TOOL_DOCS))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Odin-mode assembly
# ---------------------------------------------------------------------------


def _assemble_odin_context(db: Session, agent: Agent) -> str:
    """Assemble context for Odin, the system-level agent.

    Lighter budget (~4000 tokens) with cross-space overview.
    """
    sections: list[str] = []
    remaining = BUDGET_ODIN_TOTAL

    # Agent identity (always first)
    identity = _build_agent_identity(agent)
    identity_truncated = _truncate_to_budget(identity, min(remaining, BUDGET_AGENT_IDENTITY))
    sections.append(identity_truncated)
    remaining -= estimate_tokens(identity_truncated)

    # All spaces overview
    if remaining > 0:
        spaces_section = _build_odin_spaces_section(db)
        if spaces_section:
            truncated = _truncate_to_budget(spaces_section, remaining)
            sections.append(truncated)
            remaining -= estimate_tokens(truncated)

    # All agents overview
    if remaining > 0:
        agents_section = _build_odin_agents_section(db)
        if agents_section:
            truncated = _truncate_to_budget(agents_section, remaining)
            sections.append(truncated)
            remaining -= estimate_tokens(truncated)

    # Cross-space to-do summary
    if remaining > 0:
        todo_summary = _build_odin_todo_summary(db)
        if todo_summary:
            truncated = _truncate_to_budget(todo_summary, remaining)
            sections.append(truncated)
            remaining -= estimate_tokens(truncated)

    # Attention items
    if remaining > 0:
        attention = _build_odin_attention_items(db)
        if attention:
            truncated = _truncate_to_budget(attention, remaining)
            sections.append(truncated)
            remaining -= estimate_tokens(truncated)

    # Odin's conversation summaries
    if remaining > 0:
        summaries = _build_summaries_section(db, space_id=None)
        if summaries:
            truncated = _truncate_to_budget(summaries, remaining)
            sections.append(truncated)
            remaining -= estimate_tokens(truncated)

    # Global memory facts
    if remaining > 0:
        global_facts = _build_memory_section(db, namespace="global", header="Global Facts")
        if global_facts:
            truncated = _truncate_to_budget(global_facts, remaining)
            sections.append(truncated)

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _build_agent_identity(agent: Agent) -> str:
    """Build the agent identity section from the agent model."""
    lines = [f"## Agent: {agent.name}"]
    if agent.description:
        lines.append(agent.description)
    if agent.system_prompt:
        lines.append("")
        lines.append(agent.system_prompt)
    return "\n".join(lines)


def _build_todo_board_section(db: Session, space_id: str) -> str:
    """Build to-do list and board state for a space."""
    lines: list[str] = []

    # Open to-dos
    todos = todo_service.list_todos(db, space_id=space_id, is_done=False, limit=10000)
    if todos:
        lines.append("## Current To-dos")
        for t in todos:
            due = f" (due: {t.due_date.strftime('%Y-%m-%d')})" if t.due_date else ""
            lines.append(f"- {t.title}{due}")

    # Board items by stage
    items = item_service.list_items(db, space_id=space_id, archived=False)
    if items:
        lines.append("")
        lines.append("## Board State")
        stages: dict[str | None, list[Item]] = {}
        for item in items:
            stages.setdefault(item.stage, []).append(item)
        for stage, stage_items in stages.items():
            stage_label = stage or "No Stage"
            lines.append(f"### {stage_label}")
            for item in stage_items:
                due = f" (due: {item.due_date.strftime('%Y-%m-%d')})" if item.due_date else ""
                lines.append(f"- {item.title}{due}")

    return "\n".join(lines)


def _build_summaries_section(
    db: Session,
    *,
    space_id: str | None,
) -> str:
    """Build conversation summaries section (most recent first)."""
    summaries = conversation_service.get_summaries(db, space_id=space_id)
    if not summaries:
        return ""

    lines = ["## Previous Conversations"]
    for s in summaries:
        lines.append(f"- {s.summary}")
        if s.decisions:
            for d in s.decisions:
                lines.append(f"  - Decision: {d}")
        if s.open_questions:
            for q in s.open_questions:
                lines.append(f"  - Open: {q}")

    return "\n".join(lines)


def _build_memory_section(db: Session, *, namespace: str, header: str) -> str:
    """Build a memory facts section from memory entries in a namespace."""
    entries = memory_service.list_entries(db, namespace=namespace)
    if not entries:
        return ""

    lines = [f"## {header}"]
    for entry in entries:
        lines.append(f"- **{entry.key}**: {entry.value}")

    return "\n".join(lines)


def _build_tool_docs_section(agent: Agent) -> str:
    """Build documentation for the agent's available MCP tools."""
    if not agent.mcp_tools:
        return ""

    lines = ["## Available Tools"]
    for tool in agent.mcp_tools:
        if isinstance(tool, dict):
            name = tool.get("name", "unknown")
            desc = tool.get("description", "")
            lines.append(f"- **{name}**: {desc}")
        else:
            # Simple string tool name
            lines.append(f"- {tool}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Odin-specific section builders
# ---------------------------------------------------------------------------


def _build_odin_spaces_section(db: Session) -> str:
    """List all spaces for Odin's overview."""
    spaces = space_service.list_spaces(db)
    if not spaces:
        return ""

    lines = ["## All Spaces"]
    for s in spaces:
        desc = f" — {s.description}" if s.description else ""
        lines.append(f"- **{s.name}** (template: {s.template}){desc}")

    return "\n".join(lines)


def _build_odin_agents_section(db: Session) -> str:
    """List all agents for Odin's overview."""
    agents = agent_service.list_agents(db)
    if not agents:
        return ""

    lines = ["## All Agents"]
    for a in agents:
        space_names = [sp.name for sp in a.spaces] if a.spaces else []
        spaces_str = f" [spaces: {', '.join(space_names)}]" if space_names else ""
        lines.append(f"- **{a.name}** (status: {a.status}){spaces_str}")

    return "\n".join(lines)


def _build_odin_todo_summary(db: Session) -> str:
    """Cross-space to-do summary: open count per space, overdue items."""
    all_todos = todo_service.list_todos(db, is_done=False, limit=10000)
    if not all_todos:
        return ""

    # Count by space
    space_counts: dict[str, int] = {}
    overdue: list[Todo] = []
    now = datetime.now(UTC)

    for t in all_todos:
        space_counts[t.space_id] = space_counts.get(t.space_id, 0) + 1
        if t.due_date and _naive_utc(t.due_date) < _naive_utc(now):
            overdue.append(t)

    # Resolve space names
    space_name_cache: dict[str, str] = {}
    for sid in space_counts:
        try:
            space = space_service.get_space(db, sid)
            space_name_cache[sid] = space.name
        except Exception:
            space_name_cache[sid] = sid

    lines = ["## Cross-Space To-do Summary"]
    for sid, count in space_counts.items():
        name = space_name_cache.get(sid, sid)
        lines.append(f"- **{name}**: {count} open")

    if overdue:
        lines.append("")
        lines.append("### Overdue")
        for t in overdue:
            space_name = space_name_cache.get(t.space_id, t.space_id)
            due_str = t.due_date.strftime("%Y-%m-%d") if t.due_date else ""
            lines.append(f"- [{space_name}] {t.title} (due: {due_str})")

    return "\n".join(lines)


def _build_odin_attention_items(db: Session) -> str:
    """Attention items: items due today, pending approval requests."""
    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)

    lines: list[str] = []

    # Due-today items across all spaces
    all_items = item_service.list_items(db, archived=False)
    due_today = [
        i
        for i in all_items
        if i.due_date and _naive_utc(today_start) <= _naive_utc(i.due_date) <= _naive_utc(today_end)
    ]

    if due_today:
        lines.append("## Attention Items")
        lines.append("### Due Today")
        for item in due_today:
            lines.append(f"- {item.title} (stage: {item.stage or 'none'})")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def _truncate_to_budget(text: str, token_budget: int) -> str:
    """Truncate text to fit within a token budget.

    Truncates from the bottom (drops last lines first), which naturally
    drops the oldest/least relevant entries since sections are ordered
    most-recent-first.
    """
    if estimate_tokens(text) <= token_budget:
        return text

    char_budget = token_budget * 4
    # Truncate by lines to avoid cutting mid-line
    lines = text.split("\n")
    result_lines: list[str] = []
    char_count = 0

    for line in lines:
        # +1 for the newline character between lines
        line_chars = len(line) + (1 if result_lines else 0)
        if char_count + line_chars > char_budget:
            break
        result_lines.append(line)
        char_count += line_chars

    if len(result_lines) < len(lines):
        result_lines.append("... (truncated)")

    return "\n".join(result_lines)
