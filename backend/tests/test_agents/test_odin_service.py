"""Tests for the Odin service — agent/conversation lifecycle and message delegation."""

from unittest.mock import patch

import pytest

from backend.openloop.agents.odin_service import ODIN_SYSTEM_PROMPT, OdinService
from backend.openloop.db.models import Agent, Conversation


@pytest.fixture()
def odin_svc():
    """Return a fresh OdinService instance (not the singleton)."""
    svc = OdinService()
    svc._agent_id = None
    svc._conversation_id = None
    return svc


# ---------------------------------------------------------------------------
# ensure_agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_agent_creates_on_first_call(db_session, odin_svc):
    agent_id = await odin_svc.ensure_agent(db_session)

    agent = db_session.query(Agent).filter(Agent.id == agent_id).first()
    assert agent is not None
    assert agent.name == "Odin"
    assert agent.default_model == "haiku"
    assert agent.system_prompt == ODIN_SYSTEM_PROMPT
    expected_desc = "System-level AI assistant. Routes requests, handles simple actions."
    assert agent.description == expected_desc


@pytest.mark.asyncio
async def test_ensure_agent_returns_existing_on_second_call(db_session, odin_svc):
    first_id = await odin_svc.ensure_agent(db_session)
    second_id = await odin_svc.ensure_agent(db_session)

    assert first_id == second_id
    # Only one Odin agent in DB
    agents = db_session.query(Agent).filter(Agent.name == "Odin").all()
    assert len(agents) == 1


@pytest.mark.asyncio
async def test_ensure_agent_recovers_if_cached_id_deleted(db_session, odin_svc):
    """If the cached _agent_id is stale, re-lookup or re-create."""
    first_id = await odin_svc.ensure_agent(db_session)

    # Simulate deletion of the agent
    agent = db_session.query(Agent).filter(Agent.id == first_id).first()
    db_session.delete(agent)
    db_session.commit()

    second_id = await odin_svc.ensure_agent(db_session)
    assert second_id != first_id
    # A new Odin agent exists
    agent = db_session.query(Agent).filter(Agent.id == second_id).first()
    assert agent is not None
    assert agent.name == "Odin"


# ---------------------------------------------------------------------------
# ensure_conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ensure_conversation_creates_on_first_call(db_session, odin_svc):
    conv_id = await odin_svc.ensure_conversation(db_session)

    conv = db_session.query(Conversation).filter(Conversation.id == conv_id).first()
    assert conv is not None
    assert conv.space_id is None
    assert conv.status == "active"
    assert conv.name == "Odin"


@pytest.mark.asyncio
async def test_ensure_conversation_returns_existing_on_second_call(db_session, odin_svc):
    first_id = await odin_svc.ensure_conversation(db_session)
    second_id = await odin_svc.ensure_conversation(db_session)

    assert first_id == second_id


@pytest.mark.asyncio
async def test_ensure_conversation_creates_new_if_closed(db_session, odin_svc):
    """If the previous conversation was closed, create a new one."""
    first_id = await odin_svc.ensure_conversation(db_session)

    # Close the conversation
    conv = db_session.query(Conversation).filter(Conversation.id == first_id).first()
    conv.status = "closed"
    db_session.commit()

    # Reset cached conversation_id so it re-checks
    odin_svc._conversation_id = None

    second_id = await odin_svc.ensure_conversation(db_session)
    assert second_id != first_id


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_delegates_to_agent_runner(db_session, odin_svc):
    """send_message should call agent_runner.run_interactive with correct args."""
    mock_events = [{"type": "stream", "data": "hello"}]

    async def mock_run_interactive(db, *, conversation_id, message):
        for event in mock_events:
            yield event

    with patch(
        "backend.openloop.agents.odin_service.agent_runner.run_interactive",
        side_effect=mock_run_interactive,
    ):
        events = []
        async for event in odin_svc.send_message(db_session, "Hello Odin"):
            events.append(event)

    assert len(events) == 1
    assert events[0]["type"] == "stream"
