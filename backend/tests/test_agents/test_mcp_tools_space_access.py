"""Tests for MCP tool space access validation (_validate_space_access).

Verifies that:
- A scoped agent (linked to specific spaces) can access its spaces
- A scoped agent is denied access to spaces it's not linked to
- A system agent (no agent_spaces rows) can access any space
"""

import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.openloop.agents.mcp_tools import create_task
from backend.openloop.services import agent_service, space_service


def _parse(result: str) -> dict:
    return json.loads(result)


def _make_space(db: Session, name: str = "Test Space") -> str:
    space = space_service.create_space(db, name=name, template="project")
    return space.id


def _make_agent(db: Session, name: str = "TestAgent") -> str:
    agent = agent_service.create_agent(db, name=name)
    return agent.id


def _link_agent_to_space(db: Session, agent_id: str, space_id: str) -> None:
    """Insert into the agent_spaces join table to scope the agent."""
    db.execute(
        text("INSERT INTO agent_spaces (agent_id, space_id) VALUES (:aid, :sid)"),
        {"aid": agent_id, "sid": space_id},
    )
    db.commit()


class TestValidateSpaceAccess:
    @pytest.mark.asyncio
    async def test_scoped_agent_can_access_linked_space(self, db_session: Session):
        """Agent linked to a space should be able to create tasks in it."""
        space_id = _make_space(db_session, "Allowed Space")
        agent_id = _make_agent(db_session, "ScopedAgent")
        _link_agent_to_space(db_session, agent_id, space_id)

        result = _parse(
            await create_task(space_id, "Test Task", _db=db_session, _agent_id=agent_id)
        )
        assert "result" in result
        assert result["result"]["title"] == "Test Task"
        assert result["result"]["space_id"] == space_id

    @pytest.mark.asyncio
    async def test_scoped_agent_denied_access_to_other_space(self, db_session: Session):
        """Agent linked to Space A should be denied when creating tasks in Space B."""
        space_a = _make_space(db_session, "Space A")
        space_b = _make_space(db_session, "Space B")
        agent_id = _make_agent(db_session, "ScopedAgent")
        _link_agent_to_space(db_session, agent_id, space_a)

        result = _parse(
            await create_task(space_b, "Denied Task", _db=db_session, _agent_id=agent_id)
        )
        assert result["is_error"] is True
        assert "does not have access" in result["error"]

    @pytest.mark.asyncio
    async def test_system_agent_can_access_any_space(self, db_session: Session):
        """An agent with no agent_spaces rows (system agent) can access any space."""
        space_id = _make_space(db_session, "Any Space")
        agent_id = _make_agent(db_session, "SystemAgent")
        # No _link_agent_to_space call — system agent

        result = _parse(
            await create_task(space_id, "System Task", _db=db_session, _agent_id=agent_id)
        )
        assert "result" in result
        assert result["result"]["title"] == "System Task"

    @pytest.mark.asyncio
    async def test_empty_agent_id_treated_as_system(self, db_session: Session):
        """An empty agent_id (default) should be treated as system with no restrictions."""
        space_id = _make_space(db_session, "Open Space")

        result = _parse(
            await create_task(space_id, "No Agent", _db=db_session, _agent_id="")
        )
        assert "result" in result
        assert result["result"]["title"] == "No Agent"
