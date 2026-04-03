"""Tests for the Odin API routes."""

from unittest.mock import AsyncMock, patch

from backend.openloop.db.models import Agent, Conversation


def test_post_odin_message_returns_201(client, db_session):
    """POST /api/v1/odin/message should return 201 with the stored user message."""
    # Mock the background task that calls agent_runner
    with patch(
        "backend.openloop.api.routes.odin.odin.send_message",
        return_value=AsyncMock(),
    ):
        response = client.post(
            "/api/v1/odin/message",
            json={"content": "List my spaces"},
        )

    assert response.status_code == 201
    data = response.json()
    assert data["role"] == "user"
    assert data["content"] == "List my spaces"
    assert "id" in data
    assert "conversation_id" in data


def test_odin_agent_auto_created_on_first_message(client, db_session):
    """After first message, the Odin agent should exist in the DB."""
    # Verify no Odin agent before
    assert db_session.query(Agent).filter(Agent.name == "Odin").first() is None

    with patch(
        "backend.openloop.api.routes.odin.odin.send_message",
        return_value=AsyncMock(),
    ):
        response = client.post(
            "/api/v1/odin/message",
            json={"content": "Hello"},
        )

    assert response.status_code == 201

    # Odin agent and conversation should now exist
    agent = db_session.query(Agent).filter(Agent.name == "Odin").first()
    assert agent is not None
    assert agent.default_model == "haiku"

    conv = (
        db_session.query(Conversation)
        .filter(
            Conversation.space_id.is_(None),
            Conversation.agent_id == agent.id,
            Conversation.status == "active",
        )
        .first()
    )
    assert conv is not None
    assert conv.name == "Odin"


def test_odin_message_missing_content_returns_422(client):
    """POST with empty body should fail validation."""
    response = client.post("/api/v1/odin/message", json={})
    assert response.status_code == 422
