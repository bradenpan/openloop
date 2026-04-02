"""Tests for Phase 7.1a memory lifecycle API endpoints."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.db.models import (
    Agent,
    BehavioralRule,
    Conversation,
    MemoryEntry,
)


def _seed_space(client: TestClient) -> str:
    """Create a space via API and return its ID."""
    resp = client.post("/api/v1/spaces", json={"name": "Mem Test", "template": "project"})
    assert resp.status_code == 201
    return resp.json()["id"]


def _seed_space_with_data(client: TestClient, db_session: Session) -> str:
    """Create a space with memory entries and rules, return space_id."""
    space_id = _seed_space(client)
    ns = f"space:{space_id}"

    # Active facts
    db_session.add(MemoryEntry(namespace=ns, key="f1", value="fact one"))
    db_session.add(MemoryEntry(namespace=ns, key="f2", value="fact two"))
    # Archived fact
    db_session.add(
        MemoryEntry(namespace=ns, key="f3", value="old", archived_at=datetime.now(UTC))
    )

    # Agent with rules
    agent = Agent(name="Test Agent", status="idle")
    db_session.add(agent)
    db_session.flush()

    conv = Conversation(
        space_id=space_id, agent_id=agent.id, name="test", status="active"
    )
    db_session.add(conv)
    db_session.flush()

    db_session.add(
        BehavioralRule(agent_id=agent.id, rule="do X", source_type="correction")
    )
    db_session.add(
        BehavioralRule(
            agent_id=agent.id, rule="do Y", source_type="correction", is_active=False
        )
    )
    db_session.commit()

    return space_id


# ---------------------------------------------------------------------------
# GET /api/v1/spaces/{space_id}/memory/health
# ---------------------------------------------------------------------------


def test_memory_health_empty(client: TestClient):
    space_id = _seed_space(client)
    resp = client.get(f"/api/v1/spaces/{space_id}/memory/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_facts"] == 0
    assert data["archived_facts"] == 0
    assert data["active_rules"] == 0
    assert data["inactive_rules"] == 0


def test_memory_health_with_data(client: TestClient, db_session: Session):
    space_id = _seed_space_with_data(client, db_session)
    resp = client.get(f"/api/v1/spaces/{space_id}/memory/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["active_facts"] == 2
    assert data["archived_facts"] == 1
    assert data["active_rules"] == 1
    assert data["inactive_rules"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/spaces/{space_id}/memory/consolidate/apply
# ---------------------------------------------------------------------------


def test_apply_consolidation_merges(client: TestClient, db_session: Session):
    space_id = _seed_space(client)
    ns = f"space:{space_id}"

    e1 = MemoryEntry(namespace=ns, key="a", value="fact a")
    e2 = MemoryEntry(namespace=ns, key="b", value="fact b")
    db_session.add_all([e1, e2])
    db_session.commit()

    resp = client.post(
        f"/api/v1/spaces/{space_id}/memory/consolidate/apply",
        json={
            "merges": [
                {
                    "source_ids": [e1.id, e2.id],
                    "merged_value": "facts a and b combined",
                    "reason": "duplicates",
                }
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["merged"] == 1
    assert data["archived"] == 0


def test_apply_consolidation_stale(client: TestClient, db_session: Session):
    space_id = _seed_space(client)
    ns = f"space:{space_id}"

    e1 = MemoryEntry(namespace=ns, key="stale1", value="old")
    db_session.add(e1)
    db_session.commit()

    resp = client.post(
        f"/api/v1/spaces/{space_id}/memory/consolidate/apply",
        json={
            "stale": [{"id": e1.id, "reason": "never accessed"}],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["merged"] == 0
    assert data["archived"] == 1


def test_apply_consolidation_empty(client: TestClient):
    space_id = _seed_space(client)
    resp = client.post(
        f"/api/v1/spaces/{space_id}/memory/consolidate/apply",
        json={},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["merged"] == 0
    assert data["archived"] == 0
