from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.db.models import Agent, BackgroundTask, SystemState


def test_get_morning_brief_endpoint(client: TestClient):
    resp = client.get("/api/v1/home/morning-brief")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    assert "pending_approvals_count" in data
    assert "failed_tasks_count" in data
    assert isinstance(data["agents"], list)


def test_dismiss_morning_brief_updates_last_seen(client: TestClient, db_session: Session):
    # Call dismiss endpoint
    resp = client.post("/api/v1/home/morning-brief/dismiss")
    assert resp.status_code == 204

    # Check system_state for user_last_seen
    row = db_session.query(SystemState).filter(SystemState.key == "user_last_seen").first()
    assert row is not None
    assert row.value is not None
    # Verify it's a recent ISO timestamp
    ts = datetime.fromisoformat(row.value)
    assert (datetime.now(UTC).replace(tzinfo=None) - ts).total_seconds() < 60


def test_dashboard_does_not_update_last_seen(client: TestClient, db_session: Session):
    # Call dashboard endpoint
    resp = client.get("/api/v1/home/dashboard")
    assert resp.status_code == 200

    # Verify user_last_seen was NOT set
    row = db_session.query(SystemState).filter(SystemState.key == "user_last_seen").first()
    assert row is None
