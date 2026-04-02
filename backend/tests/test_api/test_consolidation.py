"""API tests for the consolidation endpoint.

Covers: manual trigger happy path, 409 (not enough summaries), 404 (bad space).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, Conversation, ConversationSummary, Space

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_space_with_summaries(db: Session, count: int = 3) -> tuple[str, list[str]]:
    """Create a space, agent, conversation, and N summaries. Return (space_id, summary_ids)."""
    space = Space(name="Consolidation Test", template="project")
    db.add(space)
    db.flush()

    agent = Agent(name="test-agent-consolidation")
    db.add(agent)
    db.flush()

    conv = Conversation(agent_id=agent.id, name="test-conv", space_id=space.id)
    db.add(conv)
    db.flush()

    summary_ids = []
    for i in range(count):
        s = ConversationSummary(
            conversation_id=conv.id,
            space_id=space.id,
            summary=f"summary {i}",
        )
        db.add(s)
        db.flush()
        summary_ids.append(s.id)

    db.commit()
    return space.id, summary_ids


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_consolidate_happy_path(client: TestClient, db_session: Session):
    """POST /api/v1/spaces/{id}/consolidate should create a meta-summary."""
    space_id, _ = _seed_space_with_summaries(db_session, count=5)

    mock_llm = AsyncMock(return_value={
        "summary": "Consolidated overview of 5 sessions",
        "decisions": ["d1", "d2"],
        "open_questions": ["q1"],
    })

    with patch(
        "backend.openloop.services.consolidation_service._call_consolidation_llm",
        mock_llm,
    ):
        resp = client.post(f"/api/v1/spaces/{space_id}/consolidate")

    assert resp.status_code == 200
    data = resp.json()
    assert data["is_meta_summary"] is True
    assert data["summary"] == "Consolidated overview of 5 sessions"
    assert data["decisions"] == ["d1", "d2"]
    assert data["open_questions"] == ["q1"]
    assert data["space_id"] == space_id


def test_consolidate_409_not_enough(client: TestClient, db_session: Session):
    """Should return 409 when fewer than 2 unconsolidated summaries exist."""
    space_id, _ = _seed_space_with_summaries(db_session, count=1)

    resp = client.post(f"/api/v1/spaces/{space_id}/consolidate")
    assert resp.status_code == 409
    assert "Not enough" in resp.json()["detail"]


def test_consolidate_409_zero_summaries(client: TestClient, db_session: Session):
    """Should return 409 when zero summaries exist."""
    space = Space(name="Empty Space", template="simple")
    db_session.add(space)
    db_session.commit()

    resp = client.post(f"/api/v1/spaces/{space.id}/consolidate")
    assert resp.status_code == 409


def test_consolidate_404_bad_space(client: TestClient):
    """Should return 404 for a non-existent space."""
    resp = client.post("/api/v1/spaces/nonexistent-id/consolidate")
    assert resp.status_code == 404
