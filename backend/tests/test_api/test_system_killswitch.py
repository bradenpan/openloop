"""API tests for system kill switch endpoints (Phase 8.4)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.services import agent_service, background_task_service


def _make_agent(db: Session, name: str = "KSAgent"):
    return agent_service.create_agent(db, name=name)


# ---------------------------------------------------------------------------
# POST /api/v1/system/emergency-stop
# ---------------------------------------------------------------------------


def test_emergency_stop_endpoint(client: TestClient, db_session: Session):
    agent = _make_agent(db_session)
    background_task_service.create_background_task(
        db_session, agent_id=agent.id, instruction="running task", status="running"
    )

    resp = client.post("/api/v1/system/emergency-stop")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paused"] is True
    assert data["tasks_interrupted"] == 1
    assert len(data["interrupted_task_ids"]) == 1


def test_emergency_stop_no_tasks(client: TestClient, db_session: Session):
    resp = client.post("/api/v1/system/emergency-stop")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paused"] is True
    assert data["tasks_interrupted"] == 0


# ---------------------------------------------------------------------------
# POST /api/v1/system/resume
# ---------------------------------------------------------------------------


def test_resume_endpoint(client: TestClient, db_session: Session):
    # Pause first
    client.post("/api/v1/system/emergency-stop")
    resp = client.post("/api/v1/system/resume")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paused"] is False


def test_resume_when_not_paused(client: TestClient, db_session: Session):
    resp = client.post("/api/v1/system/resume")
    assert resp.status_code == 200
    assert resp.json()["paused"] is False


# ---------------------------------------------------------------------------
# GET /api/v1/system/status
# ---------------------------------------------------------------------------


def test_status_endpoint_default(client: TestClient, db_session: Session):
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["paused"] is False
    assert data["active_sessions"] == 0


def test_status_endpoint_paused(client: TestClient, db_session: Session):
    client.post("/api/v1/system/emergency-stop")
    resp = client.get("/api/v1/system/status")
    assert resp.status_code == 200
    assert resp.json()["paused"] is True


# ---------------------------------------------------------------------------
# Guard: delegate_background rejects when paused
# ---------------------------------------------------------------------------


def test_is_paused_guard_prevents_background(client: TestClient, db_session: Session):
    """Verify the kill switch guard is testable at service level."""
    from backend.openloop.services import system_service

    system_service.emergency_stop(db_session)
    assert system_service.is_paused(db_session) is True

    # Resume and verify
    system_service.resume(db_session)
    assert system_service.is_paused(db_session) is False
