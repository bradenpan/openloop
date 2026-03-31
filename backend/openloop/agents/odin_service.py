"""Odin Service — system-level AI front door.

Odin is always available, handles simple actions directly (to-dos, navigation),
and routes complex work to space agents. Runs on Haiku. Its conversation record
has space_id=None (system-level).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.orm import Session

from backend.openloop.agents import session_manager
from backend.openloop.db.models import Agent, Conversation
from backend.openloop.services import agent_service, conversation_service

logger = logging.getLogger(__name__)

ODIN_SYSTEM_PROMPT = """\
You are Odin, the AI front door for OpenLoop — a personal command center.

You help the user by:
- Creating to-dos and managing tasks directly via your tools
- Answering questions about their spaces, agents, and work
- Routing them to the right space agent for complex work (use open_conversation tool)
- Navigating them to spaces (use navigate_to_space tool)

Keep responses concise. For simple actions (create a to-do, list spaces), handle them directly.
For complex work (planning, research, code review), route to the appropriate space agent.

If you're unsure which space or agent to use, ask a clarifying question.\
"""

ODIN_MCP_TOOLS = [
    "create_todo",
    "complete_todo",
    "list_todos",
    "create_item",
    "update_item",
    "move_item",
    "get_item",
    "list_items",
    "read_memory",
    "write_memory",
    "read_document",
    "list_documents",
    "create_document",
    "get_board_state",
    "get_todo_state",
    "get_conversation_summaries",
    "search_conversations",
    "get_conversation_messages",
    "delegate_task",
    "list_spaces",
    "list_agents",
    "open_conversation",
    "navigate_to_space",
    "get_attention_items",
    "get_cross_space_todos",
]


class OdinService:
    """Manages the Odin system-level agent session."""

    _agent_id: str | None = None
    _conversation_id: str | None = None

    async def ensure_agent(self, db: Session) -> str:
        """Ensure the Odin agent exists in DB. Create if missing. Return agent_id."""
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

    async def ensure_conversation(self, db: Session) -> str:
        """Ensure an active Odin conversation exists. Create if none. Return conversation_id."""
        agent_id = await self.ensure_agent(db)

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

        async for event in session_manager.send_message(
            db,
            conversation_id=conversation_id,
            message=message,
        ):
            yield event


# Singleton
odin = OdinService()
