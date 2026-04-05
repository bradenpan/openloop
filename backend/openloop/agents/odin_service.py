"""Odin Service — system-level AI front door.

Odin is always available, handles simple actions directly (tasks, navigation),
and routes complex work to space agents. Runs on Haiku. Its conversation record
has space_id=None (system-level).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator

from sqlalchemy.orm import Session

from backend.openloop.agents import agent_runner
from backend.openloop.db.models import Agent, Conversation
from backend.openloop.services import agent_service, conversation_service

logger = logging.getLogger(__name__)

ODIN_SYSTEM_PROMPT = """\
You are Odin, the AI front door for OpenLoop — a personal command center.

You help the user by:
- Creating tasks and managing items directly via your tools
- Answering questions about their spaces, agents, and work
- Routing them to the right space agent for complex work (use open_conversation tool)
- Navigating them to spaces (use navigate_to_space tool)

Keep responses concise. For simple actions (create a task, list spaces), handle them directly.
For complex work (planning, research, code review), route to the appropriate space agent.

If the user asks to create an agent, set up a new agent, or says "I need an agent for...",
open a conversation with the Agent Builder agent using the open_conversation tool.
Say something like: "I'll connect you with the Agent Builder to set that up."

If the user asks to connect an API, set up an integration, pull data from an external service,
or says things like "connect my [X] data", "integrate [service]", "I want to pull data from [API]",
or "set up an integration for [service]", open a conversation with the Integration Builder agent
using the open_conversation tool.
Say something like: "I'll connect you with the Integration Builder to get that set up."

If you're unsure which space or agent to use, ask a clarifying question.

When routing to an agent via open_conversation, pick a model based on the task:
- Pass model="haiku" for quick questions, status checks, simple lookups.
- Leave model empty for standard work — conversations, task management, research. The agent's default (Sonnet) handles this well.
- Pass model="opus" for complex planning across spaces, deep analysis, architecture decisions, tradeoff evaluation, or autonomous multi-step goals where getting it right on the first try matters.

Examples: "What's on my plate?" → haiku. "Help me manage these candidates" → default. "Plan Q2 strategy across all my spaces" → opus.\
"""

ODIN_MCP_TOOLS = [
    # Standard tools (shared with space agents)
    "create_task",
    "complete_task",
    "list_tasks",
    "create_item",
    "update_item",
    "move_item",
    "get_item",
    "list_items",
    "link_items",
    "unlink_items",
    "get_linked_items",
    "archive_item",
    "read_memory",
    "write_memory",
    "save_fact",
    "update_fact",
    "recall_facts",
    "delete_fact",
    "save_rule",
    "confirm_rule",
    "override_rule",
    "list_rules",
    "read_document",
    "list_documents",
    "create_document",
    "get_board_state",
    "get_task_state",
    "get_conversation_summaries",
    "search_conversations",
    "search_summaries",
    "get_conversation_messages",
    "delegate_task",
    "update_task_progress",
    "read_drive_file",
    "list_drive_files",
    "create_drive_file",
    "get_space_layout",
    "add_widget",
    "update_widget",
    "remove_widget",
    "set_space_layout",
    # Odin-only tools
    "list_spaces",
    "list_agents",
    "open_conversation",
    "navigate_to_space",
    "get_attention_items",
    "get_cross_space_tasks",
]


class OdinService:
    """Manages the Odin system-level agent session."""

    _agent_id: str | None = None
    _conversation_id: str | None = None
    _lock: asyncio.Lock = asyncio.Lock()

    def _ensure_agent_unlocked(self, db: Session) -> str:
        """Inner implementation of ensure_agent. Caller must hold self._lock."""
        if self._agent_id is not None:
            # Verify it still exists
            existing = db.query(Agent).filter(Agent.id == self._agent_id).first()
            if existing:
                return self._agent_id

        # Look for an existing Odin agent by name
        existing = db.query(Agent).filter(Agent.name == "Odin").first()
        if existing:
            self._agent_id = existing.id
            return existing.id

        # Create Odin agent
        agent = agent_service.create_agent(
            db,
            name="Odin",
            description="System-level AI assistant. Routes requests, handles simple actions.",
            system_prompt=ODIN_SYSTEM_PROMPT,
            default_model="haiku",
            mcp_tools=ODIN_MCP_TOOLS,
        )
        self._agent_id = agent.id
        return agent.id

    async def ensure_agent(self, db: Session) -> str:
        """Ensure the Odin agent exists in DB. Create if missing. Return agent_id."""
        async with self._lock:
            return self._ensure_agent_unlocked(db)

    async def ensure_conversation(self, db: Session) -> str:
        """Ensure an active Odin conversation exists. Create if none. Return conversation_id."""
        async with self._lock:
            agent_id = self._ensure_agent_unlocked(db)

            if self._conversation_id is not None:
                # Verify it still exists and is active
                existing = (
                    db.query(Conversation)
                    .filter(
                        Conversation.id == self._conversation_id,
                        Conversation.status == "active",
                    )
                    .first()
                )
                if existing:
                    return self._conversation_id

            # Look for an existing active Odin conversation (space_id=null)
            existing = (
                db.query(Conversation)
                .filter(
                    Conversation.space_id.is_(None),
                    Conversation.agent_id == agent_id,
                    Conversation.status == "active",
                )
                .first()
            )
            if existing:
                self._conversation_id = existing.id
                return existing.id

            # Create a new Odin conversation
            conv = conversation_service.create_conversation(
                db,
                agent_id=agent_id,
                name="Odin",
                space_id=None,
            )
            self._conversation_id = conv.id
            return conv.id

    async def send_message(self, db: Session, message: str) -> AsyncGenerator[dict, None]:
        """Send a message to Odin and stream the response."""
        conversation_id = await self.ensure_conversation(db)

        async for event in agent_runner.run_interactive(
            db,
            conversation_id=conversation_id,
            message=message,
        ):
            yield event


# Singleton
odin = OdinService()
