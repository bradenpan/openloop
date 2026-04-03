"""API tests for token stats endpoint (Phase 8.4)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, conversation_service, space_service


def _make_space(db: Session, name: str = "StatsSpace"):
    return space_service.create_space(db, name=name, template="simple")


def _make_agent(db: Session, name: str = "StatsAgent"):
    return agent_service.create_agent(db, name=name)


def _make_conversation(db: Session, agent_id: str, space_id: str | None = None):
    return conversation_service.create_conversation(
        db, agent_id=agent_id, name="Stats Conv", space_id=space_id
    )


# ---------------------------------------------------------------------------
# GET /api/v1/stats/tokens
# ---------------------------------------------------------------------------


def test_token_stats_empty(client: TestClient, db_session: Session):
    resp = client.get("/api/v1/stats/tokens")
    assert resp.status_code == 200
    data = resp.json()
    assert data["period"] == "24h"
    assert data["total_tokens"] == 0
    assert data["buckets"] == []


def test_token_stats_with_data(client: TestClient, db_session: Session):
    space = _make_space(db_session)
    agent = _make_agent(db_session)
    conv = _make_conversation(db_session, agent.id, space.id)

    # Add messages with token data
    conversation_service.add_message(
        db_session,
        conversation_id=conv.id,
        role="assistant",
        content="Hello",
        input_tokens=100,
        output_tokens=50,
    )
    conversation_service.add_message(
        db_session,
        conversation_id=conv.id,
        role="assistant",
        content="World",
        input_tokens=200,
        output_tokens=100,
    )

    resp = client.get("/api/v1/stats/tokens")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_input_tokens"] == 300
    assert data["total_output_tokens"] == 150
    assert data["total_tokens"] == 450
    assert len(data["buckets"]) == 1
    bucket = data["buckets"][0]
    assert bucket["agent_id"] == agent.id
    assert bucket["agent_name"] == agent.name
    assert bucket["space_id"] == space.id
    assert bucket["space_name"] == space.name
    assert bucket["message_count"] == 2


def test_token_stats_filter_by_agent(client: TestClient, db_session: Session):
    agent1 = _make_agent(db_session, name="Agent1")
    agent2 = _make_agent(db_session, name="Agent2")
    conv1 = _make_conversation(db_session, agent1.id)
    conv2 = _make_conversation(db_session, agent2.id)

    conversation_service.add_message(
        db_session, conversation_id=conv1.id, role="assistant",
        content="a", input_tokens=100, output_tokens=50,
    )
    conversation_service.add_message(
        db_session, conversation_id=conv2.id, role="assistant",
        content="b", input_tokens=200, output_tokens=100,
    )

    resp = client.get(f"/api/v1/stats/tokens?agent_id={agent1.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_input_tokens"] == 100
    assert data["total_output_tokens"] == 50
    assert len(data["buckets"]) == 1


def test_token_stats_filter_by_space(client: TestClient, db_session: Session):
    space = _make_space(db_session, name="FilterSpace")
    agent = _make_agent(db_session, name="FilterAgent")
    conv_in_space = _make_conversation(db_session, agent.id, space.id)
    conv_no_space = _make_conversation(db_session, agent.id, None)

    conversation_service.add_message(
        db_session, conversation_id=conv_in_space.id, role="assistant",
        content="a", input_tokens=100, output_tokens=50,
    )
    conversation_service.add_message(
        db_session, conversation_id=conv_no_space.id, role="assistant",
        content="b", input_tokens=200, output_tokens=100,
    )

    resp = client.get(f"/api/v1/stats/tokens?space_id={space.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_input_tokens"] == 100
    assert len(data["buckets"]) == 1


def test_token_stats_period_7d(client: TestClient, db_session: Session):
    resp = client.get("/api/v1/stats/tokens?period=7d")
    assert resp.status_code == 200
    assert resp.json()["period"] == "7d"


def test_token_stats_messages_without_tokens_excluded(client: TestClient, db_session: Session):
    """Messages without token data should not appear in stats."""
    agent = _make_agent(db_session, name="NoTokenAgent")
    conv = _make_conversation(db_session, agent.id)

    conversation_service.add_message(
        db_session, conversation_id=conv.id, role="assistant",
        content="no tokens",
    )

    resp = client.get("/api/v1/stats/tokens")
    data = resp.json()
    assert data["total_tokens"] == 0
    assert data["buckets"] == []
