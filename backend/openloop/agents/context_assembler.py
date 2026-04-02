"""Context Assembler — builds the system prompt for agent sessions.

Uses attention-optimized ordering based on "Lost in the Middle" research:
models attend strongly to the BEGINNING and END of context, poorly to the MIDDLE.

BEGINNING (high attention):
  1. Agent identity + role prompt + memory management instructions
  2. Behavioral rules (procedural memory)
  3. Tool documentation

MIDDLE (lower attention):
  4. Conversation summaries (meta-summary first, then recent unconsolidated)
  5. Space facts via scored retrieval
  6. Global facts via scored retrieval

END (high attention, closest to user's message):
  7. Board/to-do state
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, Conversation, ConversationSummary, Item
from backend.openloop.services import (
    agent_service,
    behavioral_rule_service,
    item_service,
    memory_service,
    space_service,
)

# ---------------------------------------------------------------------------
# Token budgets (approximate, using 1 token ≈ 4 chars heuristic)
# ---------------------------------------------------------------------------

# BEGINNING (high attention)
BUDGET_AGENT_IDENTITY = 1500
BUDGET_BEHAVIORAL_RULES = 500
BUDGET_TOOL_DOCS = 1000

# MIDDLE (lower attention)
BUDGET_CONVERSATION_SUMMARIES = 2000
BUDGET_SPACE_FACTS = 1000
BUDGET_GLOBAL_FACTS = 500

# END (high attention)
BUDGET_TODOS_BOARD = 1500

# Odin mode uses a lighter total budget
BUDGET_ODIN_TOTAL = 4000


def estimate_tokens(text: str) -> int:
    """Estimate token count using a character-based heuristic (1 token ≈ 4 chars)."""
    return len(text) // 4


def _naive_utc(dt: datetime) -> datetime:
    """Strip timezone info for safe comparison (SQLite stores naive datetimes)."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# ---------------------------------------------------------------------------
# Memory management instructions (injected into agent identity section)
# ---------------------------------------------------------------------------

_MEMORY_INSTRUCTIONS = """
## Memory Management Instructions
- Use save_fact() proactively when learning important information
- Use save_rule() when the user corrects your behavior (source_type="correction") or confirms a non-obvious approach (source_type="validation")
- Use confirm_rule() when the user validates a rule was correct
- Use override_rule() when the user contradicts an existing rule
""".strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def assemble_context(
    db: Session,
    *,
    agent_id: str,
    space_id: str | None = None,
    conversation_id: str | None = None,
    read_only: bool = False,
) -> str:
    """Assemble the system prompt context for an agent session.

    For space agents (space_id provided), assembles sections in attention-optimized order.
    For Odin (space_id is None), assembles a cross-space overview.

    Set read_only=True for estimation/dry-run paths to avoid incrementing
    access counters on memory entries and behavioral rules.
    """
    agent = agent_service.get_agent(db, agent_id)

    if space_id is None:
        return _assemble_odin_context(db, agent, read_only=read_only)
    return _assemble_space_context(db, agent, space_id, conversation_id, read_only=read_only)


# ---------------------------------------------------------------------------
# Space-agent assembly (attention-optimized ordering)
# ---------------------------------------------------------------------------


def _assemble_space_context(
    db: Session,
    agent: Agent,
    space_id: str,
    conversation_id: str | None,
    read_only: bool = False,
) -> str:
    """Assemble context for an agent operating within a specific space.

    Ordering follows Lost in the Middle research:
    BEGINNING (high attention) → MIDDLE (lower attention) → END (high attention).
    """
    sections: list[str] = []

    # === BEGINNING (high attention) ===

    # 1. Agent identity + role prompt + memory instructions
    identity = _build_agent_identity(agent)
    sections.append(_truncate_to_budget(identity, BUDGET_AGENT_IDENTITY))

    # 2. Behavioral rules (procedural memory)
    rules = _build_behavioral_rules_section(db, agent.id, read_only=read_only)
    if rules:
        sections.append(_truncate_to_budget(rules, BUDGET_BEHAVIORAL_RULES))

    # 3. Tool documentation
    tool_docs = _build_tool_docs_section(agent)
    if tool_docs:
        sections.append(_truncate_to_budget(tool_docs, BUDGET_TOOL_DOCS))

    # === MIDDLE (lower attention) ===

    # 4. Conversation summaries (meta-summary first, then recent unconsolidated)
    summaries = _build_summaries_section(db, space_id=space_id)
    if summaries:
        sections.append(_truncate_to_budget(summaries, BUDGET_CONVERSATION_SUMMARIES))

    # 5. Space facts via scored retrieval
    space_facts = _build_scored_memory_section(
        db, namespace=f"space:{space_id}", header="Space Facts", read_only=read_only
    )
    if space_facts:
        sections.append(_truncate_to_budget(space_facts, BUDGET_SPACE_FACTS))

    # 6. Global facts via scored retrieval
    global_facts = _build_scored_memory_section(
        db, namespace="global", header="Global Facts", read_only=read_only
    )
    if global_facts:
        sections.append(_truncate_to_budget(global_facts, BUDGET_GLOBAL_FACTS))

    # === END (high attention, closest to user's message) ===

    # 7. Board/to-do state
    todo_board = _build_todo_board_section(db, space_id)
    if todo_board:
        sections.append(_truncate_to_budget(todo_board, BUDGET_TODOS_BOARD))

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Odin-mode assembly (attention-optimized)
# ---------------------------------------------------------------------------


def _assemble_odin_context(db: Session, agent: Agent, read_only: bool = False) -> str:
    """Assemble context for Odin, the system-level agent.

    Lighter budget (~4000 tokens) with cross-space overview.
    Uses attention-optimized ordering within the total budget.
    """
    sections: list[str] = []
    remaining = BUDGET_ODIN_TOTAL

    # === BEGINNING (high attention) ===

    # Agent identity (always first)
    identity = _build_agent_identity(agent)
    identity_truncated = _truncate_to_budget(identity, min(remaining, BUDGET_AGENT_IDENTITY))
    sections.append(identity_truncated)
    remaining -= estimate_tokens(identity_truncated)

    # Behavioral rules for Odin
    if remaining > 0:
        rules = _build_behavioral_rules_section(db, agent.id, read_only=read_only)
        if rules:
            truncated = _truncate_to_budget(rules, min(remaining, BUDGET_BEHAVIORAL_RULES))
            sections.append(truncated)
            remaining -= estimate_tokens(truncated)

    # === MIDDLE (lower attention) ===

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

    # Odin's conversation summaries
    if remaining > 0:
        summaries = _build_summaries_section(db, space_id=None)
        if summaries:
            truncated = _truncate_to_budget(summaries, remaining)
            sections.append(truncated)
            remaining -= estimate_tokens(truncated)

    # Global memory facts via scored retrieval
    if remaining > 0:
        global_facts = _build_scored_memory_section(
            db, namespace="global", header="Global Facts", read_only=read_only
        )
        if global_facts:
            truncated = _truncate_to_budget(global_facts, remaining)
            sections.append(truncated)
            remaining -= estimate_tokens(truncated)

    # === END (high attention) ===

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

    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _load_skill_prompt(skill_path: str) -> str | None:
    """Load a system prompt from a SKILL.md file, stripping YAML frontmatter.

    skill_path is relative to the project root, e.g. 'agents/skills/eng-manager'.
    Returns the markdown content after frontmatter, or None if file not found.
    """
    import os

    # Validate skill_path to prevent directory traversal
    if ".." in skill_path or skill_path.startswith("/") or skill_path.startswith("\\"):
        return None

    # Resolve relative to project root (3 levels up from this file)
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    skill_md = os.path.join(project_root, skill_path, "SKILL.md")

    # Verify the resolved path is still under the project root
    real_path = os.path.realpath(skill_md)
    if not real_path.startswith(os.path.realpath(project_root)):
        return None

    if not os.path.exists(skill_md):
        return None

    with open(skill_md, encoding="utf-8") as f:
        content = f.read()

    # Strip YAML frontmatter (everything between first pair of --- lines)
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3:].lstrip("\n")

    return content


def _build_agent_identity(agent: Agent) -> str:
    """Build the agent identity section from the agent model.

    If the agent has a skill_path, loads the system prompt from SKILL.md.
    Otherwise falls back to agent.system_prompt column.
    Includes memory management instructions within the identity budget.
    """
    lines = [f"## Agent: {agent.name}"]
    if agent.description:
        lines.append(agent.description)

    # Resolve system prompt: skill_path takes priority over system_prompt column
    prompt = None
    if agent.skill_path:
        prompt = _load_skill_prompt(agent.skill_path)
    if prompt is None and agent.system_prompt:
        prompt = agent.system_prompt

    if prompt:
        lines.append("")
        lines.append(prompt)

    lines.append("")
    lines.append(_MEMORY_INSTRUCTIONS)
    return "\n".join(lines)


def _build_behavioral_rules_section(db: Session, agent_id: str, read_only: bool = False) -> str:
    """Build the behavioral rules (procedural memory) section.

    Calls apply_rules() which increments apply_count and last_applied
    (unless read_only=True for estimation paths).

    Phase 7.1a: Lazy auto-demotion — if confidence < 0.3 AND apply_count >= 10,
    deactivate the rule and exclude it from context.
    """
    rules = behavioral_rule_service.apply_rules(db, agent_id=agent_id, read_only=read_only)
    if not rules:
        return ""

    # Auto-demotion check: deactivate low-confidence rules with enough history
    active_rules = []
    demoted = False
    for rule in rules:
        if rule.confidence < 0.3 and rule.apply_count >= 10:
            rule.is_active = False
            demoted = True
            continue
        active_rules.append(rule)

    if demoted:
        db.commit()

    if not active_rules:
        return ""

    lines = [
        "## Behavioral Rules",
        "These rules reflect learned preferences and corrections. Follow them.",
    ]
    for rule in active_rules:
        lines.append(f"- [confidence: {rule.confidence}] {rule.rule}")
    return "\n".join(lines)


def _build_todo_board_section(db: Session, space_id: str) -> str:
    """Build task list and board state for a space."""
    lines: list[str] = []

    # All items by stage (tasks and records together)
    items = item_service.list_items(db, space_id=space_id, archived=False)
    if items:
        # Open tasks first
        open_tasks = [i for i in items if i.item_type == "task" and not i.is_done]
        if open_tasks:
            lines.append("## Current Tasks")
            for t in open_tasks:
                due = f" (due: {t.due_date.strftime('%Y-%m-%d')})" if t.due_date else ""
                stage_str = f" [{t.stage}]" if t.stage else ""
                lines.append(f"- {t.title}{stage_str}{due}")

        # Board state (all items grouped by stage)
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
                done_str = " [DONE]" if item.is_done else ""
                lines.append(f"- {item.title}{done_str}{due}")

    return "\n".join(lines)


def _build_summaries_section(
    db: Session,
    *,
    space_id: str | None,
) -> str:
    """Build conversation summaries section with meta-summary support.

    If a meta-summary exists, show it first as "Project Overview",
    then recent unconsolidated summaries as "Recent Conversations".
    Falls back to flat list if no meta-summary columns are present.
    """
    lines: list[str] = []

    # Load meta-summary: is_meta_summary=True AND consolidated_into IS NULL
    meta = (
        db.query(ConversationSummary)
        .filter(
            ConversationSummary.space_id == space_id,
            ConversationSummary.is_meta_summary.is_(True),
            ConversationSummary.consolidated_into.is_(None),
        )
        .first()
    )

    # Load unconsolidated individual summaries.
    # Phase 7.1a: Exclude checkpoints for closed conversations (mid-conversation
    # snapshots are only useful while the conversation is still active).
    from sqlalchemy import and_, or_

    unconsolidated = (
        db.query(ConversationSummary)
        .outerjoin(Conversation, ConversationSummary.conversation_id == Conversation.id)
        .filter(
            ConversationSummary.space_id == space_id,
            ConversationSummary.is_meta_summary.is_(False),
            ConversationSummary.consolidated_into.is_(None),
            # Keep non-checkpoints always; keep checkpoints only for active conversations
            or_(
                ConversationSummary.is_checkpoint.is_(False),
                and_(
                    ConversationSummary.is_checkpoint.is_(True),
                    Conversation.status == "active",
                ),
            ),
        )
        .order_by(ConversationSummary.created_at.desc())
        .all()
    )

    if not meta and not unconsolidated:
        return ""

    if meta:
        lines.append("## Project Overview")
        lines.append(meta.summary)
        if meta.decisions:
            for d in meta.decisions:
                lines.append(f"  - Decision: {d}")
        if meta.open_questions:
            for q in meta.open_questions:
                lines.append(f"  - Open: {q}")

    if unconsolidated:
        lines.append("")
        lines.append("## Recent Conversations")
        for s in unconsolidated:
            lines.append(f"- {s.summary}")
            if s.decisions:
                for d in s.decisions:
                    lines.append(f"  - Decision: {d}")
            if s.open_questions:
                for q in s.open_questions:
                    lines.append(f"  - Open: {q}")

    return "\n".join(lines).strip()


def _build_scored_memory_section(
    db: Session, *, namespace: str, header: str, read_only: bool = False
) -> str:
    """Build a memory facts section using scored retrieval.

    Uses get_scored_entries() which ranks by the scoring formula and
    automatically updates access tracking (unless read_only=True).
    """
    entries = memory_service.get_scored_entries(db, namespace=namespace, read_only=read_only)
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
    """Cross-space task summary: open count per space, overdue items."""
    all_tasks = item_service.list_items(db, item_type="task", is_done=False, archived=False, limit=200)
    if not all_tasks:
        return ""

    # Count by space
    space_counts: dict[str, int] = {}
    overdue: list[Item] = []
    now = datetime.now(UTC)

    for t in all_tasks:
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

    lines = ["## Cross-Space Task Summary"]
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
