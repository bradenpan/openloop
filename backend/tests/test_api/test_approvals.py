"""API route tests for the approval queue."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.db.models import BackgroundTask
from backend.openloop.services import agent_service, approval_service, space_service
from contract.enums import ApprovalStatus, BackgroundTaskStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent(db: Session, name: str = "ApprovalRouteAgent") -> str:
    agent = agent_service.create_agent(db, name=name)
    return agent.id


def _make_background_task(db: Session, agent_id: str, space_name: str = "ApprovalRouteSpace") -> str:
    space = space_service.create_space(db, name=space_name, template="project")
    task = BackgroundTask(
        agent_id=agent_id,
        instruction="test route task",
        status=BackgroundTaskStatus.RUNNING,
        space_id=space.id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task.id


def _make_approval(db: Session, agent_id: str, task_id: str, action_type: str = "execute:bash"):
    return approval_service.create_approval(
        db,
        background_task_id=task_id,
        agent_id=agent_id,
        action_type=action_type,
        action_detail={"tool_name": "Bash", "command": "ls"},
        reason="Test reason",
    )


# ---------------------------------------------------------------------------
# GET /api/v1/approval-queue
# ---------------------------------------------------------------------------


def test_list_pending_empty(client: TestClient):
    resp = client.get("/api/v1/approval-queue")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_pending_returns_pending(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    _make_approval(db_session, agent_id, task_id, "action_a")
    _make_approval(db_session, agent_id, task_id, "action_b")

    resp = client.get("/api/v1/approval-queue")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert "id" in data[0]
    assert "action_type" in data[0]
    assert "status" in data[0]
    assert "created_at" in data[0]
    assert "agent_id" in data[0]
    assert "background_task_id" in data[0]


def test_list_pending_filter_by_agent_id(client: TestClient, db_session: Session):
    agent1 = _make_agent(db_session, "RouteAgent1")
    agent2 = _make_agent(db_session, "RouteAgent2")
    task1 = _make_background_task(db_session, agent1, "Space1")
    task2 = _make_background_task(db_session, agent2, "Space2")
    _make_approval(db_session, agent1, task1)
    _make_approval(db_session, agent2, task2)

    resp = client.get("/api/v1/approval-queue", params={"agent_id": agent1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["agent_id"] == agent1


def test_list_pending_filter_by_background_task_id(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    task1 = _make_background_task(db_session, agent_id, "TaskSpace1")
    task2 = _make_background_task(db_session, agent_id, "TaskSpace2")
    _make_approval(db_session, agent_id, task1)
    _make_approval(db_session, agent_id, task2)

    resp = client.get("/api/v1/approval-queue", params={"background_task_id": task1})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["background_task_id"] == task1


# ---------------------------------------------------------------------------
# POST /api/v1/approval-queue/{id}/resolve
# ---------------------------------------------------------------------------


def test_resolve_approval_approved(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    entry = _make_approval(db_session, agent_id, task_id)

    resp = client.post(
        f"/api/v1/approval-queue/{entry.id}/resolve",
        json={"status": "approved"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "approved"
    assert data["resolved_at"] is not None
    assert data["resolved_by"] == "user"


def test_resolve_approval_denied(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    entry = _make_approval(db_session, agent_id, task_id)

    resp = client.post(
        f"/api/v1/approval-queue/{entry.id}/resolve",
        json={"status": "denied", "resolved_by": "admin"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "denied"
    assert data["resolved_by"] == "admin"


def test_resolve_approval_not_found(client: TestClient):
    resp = client.post(
        "/api/v1/approval-queue/nonexistent-id/resolve",
        json={"status": "approved"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/approval-queue/batch-resolve
# ---------------------------------------------------------------------------


def test_batch_resolve(client: TestClient, db_session: Session):
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    entry1 = _make_approval(db_session, agent_id, task_id, "action_a")
    entry2 = _make_approval(db_session, agent_id, task_id, "action_b")

    resp = client.post(
        "/api/v1/approval-queue/batch-resolve",
        json={
            "approval_ids": [entry1.id, entry2.id],
            "status": "approved",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(d["status"] == "approved" for d in data)


def test_batch_resolve_partial(client: TestClient, db_session: Session):
    """Batch resolve with mix of valid and invalid IDs — returns only valid ones."""
    agent_id = _make_agent(db_session)
    task_id = _make_background_task(db_session, agent_id)
    entry = _make_approval(db_session, agent_id, task_id)

    resp = client.post(
        "/api/v1/approval-queue/batch-resolve",
        json={
            "approval_ids": [entry.id, "nonexistent-id"],
            "status": "denied",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == entry.id
    assert data[0]["status"] == "denied"
