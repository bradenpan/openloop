"""Seed script — populates the database with representative test data.

Idempotent: clears all data and re-seeds on each run.
Uses service-layer functions where possible; falls back to direct model creation
where services don't cover it (e.g. setting is_read on notifications).
"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Add project root to path so imports resolve
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.openloop.database import Base, SessionLocal, engine
from backend.openloop.db.models import (
    Agent,
    AgentPermission,
    Automation,
    AutomationRun,
    BackgroundTask,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    DataSource,
    Document,
    Item,
    ItemEvent,
    MemoryEntry,
    Notification,
    PermissionRequest,
    Space,
    agent_spaces,
    document_items,
)
from backend.openloop.services import (
    agent_service,
    conversation_service,
    item_service,
    memory_service,
    notification_service,
    space_service,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_now = datetime.now(UTC)


def _days_ago(n: int) -> datetime:
    return _now - timedelta(days=n)


def _days_from_now(n: int) -> datetime:
    return _now + timedelta(days=n)


# ---------------------------------------------------------------------------
# Clear
# ---------------------------------------------------------------------------


def clear_all(db):
    """Delete all data from all tables in dependency-safe order."""
    # Delete from join tables first
    db.execute(document_items.delete())
    db.execute(agent_spaces.delete())

    # Delete from tables with foreign keys before their parents
    db.query(AutomationRun).delete()
    db.query(BackgroundTask).delete()
    db.query(Automation).delete()
    db.query(PermissionRequest).delete()
    db.query(ConversationMessage).delete()
    db.query(ConversationSummary).delete()
    db.query(Notification).delete()
    db.query(ItemEvent).delete()
    db.query(Document).delete()
    db.query(DataSource).delete()
    db.query(MemoryEntry).delete()
    db.query(Item).delete()
    db.query(Conversation).delete()
    db.query(AgentPermission).delete()
    db.query(Agent).delete()
    db.query(Space).delete()
    db.commit()
    print("  Cleared all tables.")


# ---------------------------------------------------------------------------
# Seed
# ---------------------------------------------------------------------------


def seed(db):
    """Create representative test data for frontend development."""

    # ------------------------------------------------------------------
    # 1. Spaces
    # ------------------------------------------------------------------
    print("  Creating spaces...")
    recruiting = space_service.create_space(
        db, name="Recruiting", template="crm", description="Track candidates and hiring pipeline"
    )
    openloop = space_service.create_space(
        db,
        name="OpenLoop",
        template="project",
        description="OpenLoop product development tasks",
    )
    personal = space_service.create_space(
        db, name="Personal", template="simple", description="Personal notes and quick tasks"
    )

    # ------------------------------------------------------------------
    # 2. Agents (before conversations, since conversations need agent_id)
    # ------------------------------------------------------------------
    print("  Creating agents...")
    recruiting_agent = agent_service.create_agent(
        db,
        name="Recruiting Agent",
        description="Automates candidate outreach and pipeline management",
        system_prompt="You are a recruiting assistant. Help manage candidates, schedule interviews, and track the hiring pipeline.",
        default_model="sonnet",
        tools=["create_item", "move_item", "memory_read", "memory_write"],
        space_ids=[recruiting.id],
    )
    code_agent = agent_service.create_agent(
        db,
        name="Code Agent",
        description="Handles code review, PR summaries, and technical tasks",
        system_prompt="You are a software engineering assistant. Help with code review, technical planning, and development tasks.",
        default_model="opus",
        tools=["create_item", "move_item", "memory_read", "memory_write", "execute_code"],
        mcp_tools=["github"],
        space_ids=[openloop.id],
    )

    # ------------------------------------------------------------------
    # 2b. Agent permissions
    # ------------------------------------------------------------------
    print("  Creating agent permissions...")
    # Recruiting Agent: broad CRM access, no code execution
    agent_service.set_permission(
        db,
        agent_id=recruiting_agent.id,
        resource_pattern="spaces/*/items",
        operation="create",
        grant_level="always",
    )
    agent_service.set_permission(
        db,
        agent_id=recruiting_agent.id,
        resource_pattern="spaces/*/items",
        operation="edit",
        grant_level="always",
    )
    agent_service.set_permission(
        db,
        agent_id=recruiting_agent.id,
        resource_pattern="spaces/*/items/move",
        operation="execute",
        grant_level="always",
    )
    agent_service.set_permission(
        db,
        agent_id=recruiting_agent.id,
        resource_pattern="external/*",
        operation="execute",
        grant_level="never",
    )

    # Code Agent: needs approval for destructive operations
    agent_service.set_permission(
        db,
        agent_id=code_agent.id,
        resource_pattern="spaces/*/items",
        operation="create",
        grant_level="always",
    )
    agent_service.set_permission(
        db,
        agent_id=code_agent.id,
        resource_pattern="spaces/*/items",
        operation="delete",
        grant_level="approval",
    )
    agent_service.set_permission(
        db,
        agent_id=code_agent.id,
        resource_pattern="external/github",
        operation="execute",
        grant_level="approval",
    )

    # ------------------------------------------------------------------
    # 3. Task items (10-15 across spaces, replacing old todos)
    # ------------------------------------------------------------------
    print("  Creating task items...")
    # Recruiting space tasks
    t1 = item_service.create_item(
        db, space_id=recruiting.id, title="Review resume: Sarah Chen — Senior Frontend",
        item_type="task",
    )
    item_service.update_item(db, t1.id, is_done=True)

    t2 = item_service.create_item(
        db, space_id=recruiting.id, title="Schedule phone screen with Marcus Johnson",
        item_type="task", due_date=_days_from_now(2),
    )
    t3 = item_service.create_item(
        db, space_id=recruiting.id, title="Send offer letter to Priya Patel",
        item_type="task", due_date=_days_from_now(1),
    )
    t4 = item_service.create_item(
        db, space_id=recruiting.id, title="Post Senior Backend role to LinkedIn",
        item_type="task",
    )

    # OpenLoop space tasks
    t5 = item_service.create_item(
        db, space_id=openloop.id, title="Write API tests for conversation endpoints",
        item_type="task",
    )
    t6 = item_service.create_item(
        db, space_id=openloop.id, title="Fix SSE reconnection bug on Safari",
        item_type="task", due_date=_days_from_now(3),
    )
    t7 = item_service.create_item(
        db, space_id=openloop.id, title="Update README with setup instructions",
        item_type="task",
    )
    item_service.update_item(db, t7.id, is_done=True)

    t8 = item_service.create_item(
        db, space_id=openloop.id, title="Benchmark SQLite query performance",
        item_type="task", due_date=_days_from_now(7),
    )

    # Personal space tasks
    t9 = item_service.create_item(
        db, space_id=personal.id, title="Buy groceries",
        item_type="task",
    )
    item_service.update_item(db, t9.id, is_done=True)

    t10 = item_service.create_item(
        db, space_id=personal.id, title="Call dentist for appointment",
        item_type="task", due_date=_days_from_now(5),
    )
    t11 = item_service.create_item(
        db, space_id=personal.id, title="Read chapter 4 of Designing Data-Intensive Applications",
        item_type="task",
    )
    t12 = item_service.create_item(
        db, space_id=personal.id, title="Renew gym membership",
        item_type="task", due_date=_days_ago(2),
    )
    item_service.update_item(db, t12.id, is_done=True)

    # ------------------------------------------------------------------
    # 4. Board items (8-10 across spaces that have boards)
    # ------------------------------------------------------------------
    print("  Creating board items...")

    # Recruiting space (CRM board: lead -> contacted -> qualifying -> negotiation -> closed)
    item_service.create_item(
        db,
        space_id=recruiting.id,
        title="Sarah Chen — Senior Frontend",
        item_type="record",
        stage="qualifying",
        description="3 YOE React/TypeScript. Strong portfolio. Phone screen completed.",
        custom_fields={"role": "Senior Frontend", "source": "LinkedIn"},
    )
    item_service.create_item(
        db,
        space_id=recruiting.id,
        title="Marcus Johnson — Backend Engineer",
        item_type="record",
        stage="contacted",
        description="Referral from engineering team. 5 YOE Python/Go.",
        custom_fields={"role": "Backend Engineer", "source": "Referral"},
    )
    item_service.create_item(
        db,
        space_id=recruiting.id,
        title="Priya Patel — Engineering Manager",
        item_type="record",
        stage="negotiation",
        description="Final round completed. Strong leadership signals. Negotiating comp.",
        custom_fields={"role": "Engineering Manager", "source": "Recruiter"},
        priority=1,
    )
    item_service.create_item(
        db,
        space_id=recruiting.id,
        title="Draft technical interview rubric",
        item_type="task",
        stage="lead",
        description="Create standardized rubric for system design interviews.",
    )

    # OpenLoop space (Project board: idea -> scoping -> todo -> in_progress -> done)
    item_service.create_item(
        db,
        space_id=openloop.id,
        title="SSE streaming for agent responses",
        item_type="task",
        stage="in_progress",
        description="Implement Server-Sent Events for real-time token streaming from agent sessions.",
        priority=1,
        due_date=_days_from_now(5),
    )
    item_service.create_item(
        db,
        space_id=openloop.id,
        title="Board drag-and-drop",
        item_type="task",
        stage="todo",
        description="Add drag-and-drop reordering for board columns using dnd-kit.",
        priority=2,
    )
    item_service.create_item(
        db,
        space_id=openloop.id,
        title="Memory search with fuzzy matching",
        item_type="task",
        stage="scoping",
        description="Evaluate FTS5 vs. trigram search for memory entries.",
    )
    item_service.create_item(
        db,
        space_id=openloop.id,
        title="Dark mode support",
        item_type="task",
        stage="idea",
        description="Add theme toggle. Tailwind dark: variant already set up.",
    )
    item_service.create_item(
        db,
        space_id=openloop.id,
        title="MCP GitHub integration",
        item_type="task",
        stage="todo",
        description="Connect GitHub MCP server for PR summaries and issue tracking.",
        assigned_agent_id=code_agent.id,
        is_agent_task=True,
    )
    item_service.create_item(
        db,
        space_id=openloop.id,
        title="v0.1 release checklist",
        item_type="task",
        stage="done",
        description="Database models, API routes, basic frontend shell.",
    )

    # ------------------------------------------------------------------
    # 5. Conversations (3 conversations with messages)
    # ------------------------------------------------------------------
    print("  Creating conversations...")

    # Active conversation in Recruiting space
    conv_active = conversation_service.create_conversation(
        db,
        agent_id=recruiting_agent.id,
        name="Candidate pipeline review",
        space_id=recruiting.id,
    )
    conversation_service.add_message(
        db,
        conversation_id=conv_active.id,
        role="user",
        content="Can you summarize the current state of our hiring pipeline? How many candidates are in each stage?",
    )
    conversation_service.add_message(
        db,
        conversation_id=conv_active.id,
        role="assistant",
        content="Here's the current pipeline breakdown:\n\n- **Lead**: 1 (Draft technical interview rubric — task)\n- **Contacted**: 1 (Marcus Johnson — Backend Engineer)\n- **Qualifying**: 1 (Sarah Chen — Senior Frontend)\n- **Negotiation**: 1 (Priya Patel — Engineering Manager)\n- **Closed**: 0\n\nPriya Patel is the furthest along — she's in negotiation. Want me to draft a compensation comparison or follow up on any of these candidates?",
    )
    conversation_service.add_message(
        db,
        conversation_id=conv_active.id,
        role="user",
        content="Yes, let's focus on Priya. What's the typical timeline for closing a negotiation?",
    )

    # Closed conversation in OpenLoop space (with summary)
    conv_closed = conversation_service.create_conversation(
        db,
        agent_id=code_agent.id,
        name="Architecture decisions for v0.1",
        space_id=openloop.id,
    )
    conversation_service.add_message(
        db,
        conversation_id=conv_closed.id,
        role="user",
        content="I'm deciding between SQLite and Postgres for the database. This is a single-user local app. Thoughts?",
    )
    conversation_service.add_message(
        db,
        conversation_id=conv_closed.id,
        role="assistant",
        content="SQLite is the right call for a single-user local app. Key reasons:\n\n1. **Zero config** — no server process, just a file\n2. **WAL mode** gives you concurrent reads with a single writer\n3. **Backup** is just copying a file\n4. **Performance** is excellent for single-user workloads\n\nThe only tradeoff: if you ever need multi-user or network access, you'd need to migrate. But for a personal command center, that's unlikely. I'd go with SQLite + WAL mode + busy_timeout=5000.",
    )
    conversation_service.add_message(
        db,
        conversation_id=conv_closed.id,
        role="user",
        content="Agreed. Let's go with SQLite. Thanks for the analysis.",
    )
    conversation_service.close_conversation(db, conv_closed.id)

    # Add summary to the closed conversation
    conversation_service.add_summary(
        db,
        conversation_id=conv_closed.id,
        summary="Decided to use SQLite for the database. Key factors: zero config, WAL mode for concurrency, file-based backup, excellent single-user performance.",
        decisions=["Use SQLite as the database", "Enable WAL mode", "Set busy_timeout=5000"],
        open_questions=["Migration strategy if multi-user is ever needed"],
    )

    # Interrupted conversation (no space — global)
    conv_interrupted = conversation_service.create_conversation(
        db,
        agent_id=code_agent.id,
        name="Debug memory leak in SSE handler",
    )
    conversation_service.add_message(
        db,
        conversation_id=conv_interrupted.id,
        role="user",
        content="I'm seeing memory growth when clients disconnect from SSE without closing cleanly. Can you help debug?",
    )
    conversation_service.add_message(
        db,
        conversation_id=conv_interrupted.id,
        role="assistant",
        content="That's a common issue with SSE. The server-side generator keeps running even after the client disconnects. You need to:\n\n1. Wrap the SSE generator in a try/finally\n2. Check for `asyncio.CancelledError` in the streaming loop\n3. Clean up the session reference when the generator exits\n\nLet me look at your current SSE handler code...",
    )
    # Set status to interrupted directly (no service method for this)
    conversation_service.update_conversation(db, conv_interrupted.id, status="interrupted")

    # ------------------------------------------------------------------
    # 6. Memory entries (5-6 in space and global namespaces)
    # ------------------------------------------------------------------
    print("  Creating memory entries...")

    # Global namespace
    memory_service.create_entry(
        db,
        namespace="global",
        key="user_name",
        value="Brad",
        tags=["identity"],
        source="user",
    )
    memory_service.create_entry(
        db,
        namespace="global",
        key="preferred_model",
        value="opus for complex tasks, sonnet for routine work",
        tags=["preferences"],
        source="user",
    )
    memory_service.create_entry(
        db,
        namespace="global",
        key="timezone",
        value="America/Chicago",
        tags=["preferences", "scheduling"],
        source="user",
    )

    # Space-specific namespaces
    memory_service.create_entry(
        db,
        namespace=recruiting.id,
        key="hiring_priorities",
        value="Senior Frontend (urgent), Backend Engineer (Q2), Engineering Manager (ongoing)",
        tags=["priorities", "hiring"],
        source="agent",
    )
    memory_service.create_entry(
        db,
        namespace=recruiting.id,
        key="interview_process",
        value="Phone screen -> Technical (2hr) -> System design (1hr) -> Culture fit (45min) -> Offer",
        tags=["process"],
        source="user",
    )
    memory_service.create_entry(
        db,
        namespace=openloop.id,
        key="tech_stack",
        value="FastAPI + SQLAlchemy + SQLite (backend), React 19 + Zustand + TanStack Query (frontend), Claude Agent SDK",
        tags=["architecture"],
        source="agent",
    )

    # ------------------------------------------------------------------
    # 7. Notifications (1 read, 1 unread)
    # ------------------------------------------------------------------
    print("  Creating notifications...")

    notif_unread = notification_service.create_notification(
        db,
        type="approval_request",
        title="Code Agent wants to create a GitHub issue",
        body="The Code Agent is requesting permission to create a GitHub issue titled 'Fix SSE reconnection on Safari'. Approve or deny.",
        space_id=openloop.id,
        conversation_id=conv_interrupted.id,
    )

    notif_read = notification_service.create_notification(
        db,
        type="task_completed",
        title="Pipeline review completed",
        body="Recruiting Agent finished reviewing the candidate pipeline. 4 candidates across 4 stages.",
        space_id=recruiting.id,
        conversation_id=conv_active.id,
    )
    # Mark the second one as read (no service param for creating as read)
    notification_service.mark_read(db, notif_read.id)

    print("  Done.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        clear_all(db)
        seed(db)
        print("Seed complete.")
    finally:
        db.close()
