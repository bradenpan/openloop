"""API tests for automations and notifications/mark-all-read."""

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.db.models import AutomationRun
from backend.openloop.services import automation_service, notification_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_agent(client: TestClient, name: str = "TestAgent") -> dict:
    resp = client.post("/api/v1/agents", json={"name": name})
    assert resp.status_code == 201
    return resp.json()


def _create_automation(client: TestClient, agent_id: str, name: str = "My Auto") -> dict:
    resp = client.post(
        "/api/v1/automations",
        json={
            "name": name,
            "agent_id": agent_id,
            "instruction": "Do something useful.",
            "trigger_type": "event",
        },
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/v1/automations
# ---------------------------------------------------------------------------


def test_create_automation(client: TestClient):
    agent = _create_agent(client)
    resp = client.post(
        "/api/v1/automations",
        json={
            "name": "Daily Digest",
            "agent_id": agent["id"],
            "instruction": "Send daily digest.",
            "trigger_type": "cron",
            "cron_expression": "0 9 * * *",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Daily Digest"
    assert data["agent_id"] == agent["id"]
    assert data["trigger_type"] == "cron"
    assert data["cron_expression"] == "0 9 * * *"
    assert data["enabled"] is True
    assert data["id"] is not None
    assert data["runs"] == []


def test_create_automation_defaults(client: TestClient):
    agent = _create_agent(client, name="DefaultAgent")
    resp = client.post(
        "/api/v1/automations",
        json={
            "name": "Simple Auto",
            "agent_id": agent["id"],
            "instruction": "Run something.",
            "trigger_type": "event",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["enabled"] is True
    assert data["cron_expression"] is None
    assert data["description"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/automations
# ---------------------------------------------------------------------------


def test_list_automations_empty(client: TestClient):
    resp = client.get("/api/v1/automations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_automations(client: TestClient):
    agent = _create_agent(client)
    _create_automation(client, agent["id"], name="A")
    _create_automation(client, agent["id"], name="B")
    resp = client.get("/api/v1/automations")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_automations_filter_enabled(client: TestClient):
    agent = _create_agent(client)
    _create_automation(client, agent["id"], name="Enabled")
    # Create a disabled one directly via service — API always creates enabled=True by default
    # We'll use PATCH to disable it
    disabled = _create_automation(client, agent["id"], name="Disabled")
    client.patch(f"/api/v1/automations/{disabled['id']}", json={"enabled": False})

    resp = client.get("/api/v1/automations", params={"enabled": True})
    assert resp.status_code == 200
    names = [a["name"] for a in resp.json()]
    assert "Enabled" in names
    assert "Disabled" not in names


# ---------------------------------------------------------------------------
# GET /api/v1/automations/{id}
# ---------------------------------------------------------------------------


def test_get_automation(client: TestClient):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"], name="Detail Test")
    resp = client.get(f"/api/v1/automations/{created['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Detail Test"
    assert "runs" in data
    assert isinstance(data["runs"], list)
    assert data["runs"] == []


def test_get_automation_not_found(client: TestClient):
    resp = client.get("/api/v1/automations/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/v1/automations/{id}
# ---------------------------------------------------------------------------


def test_update_automation_partial(client: TestClient):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"], name="Original Name")
    resp = client.patch(
        f"/api/v1/automations/{created['id']}",
        json={"name": "Updated Name"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Updated Name"
    # Other fields unchanged
    assert data["trigger_type"] == "event"
    assert data["instruction"] == "Do something useful."


def test_update_automation_enable_disable(client: TestClient):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"])
    resp = client.patch(
        f"/api/v1/automations/{created['id']}",
        json={"enabled": False},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False
    # Name still unchanged
    assert resp.json()["name"] == created["name"]


def test_update_automation_empty_body_is_noop(client: TestClient):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"], name="NoOp")
    resp = client.patch(f"/api/v1/automations/{created['id']}", json={})
    assert resp.status_code == 200
    assert resp.json()["name"] == "NoOp"


def test_update_automation_not_found(client: TestClient):
    resp = client.patch("/api/v1/automations/nonexistent-id", json={"name": "X"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/automations/{id}
# ---------------------------------------------------------------------------


def test_delete_automation(client: TestClient):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"])
    resp = client.delete(f"/api/v1/automations/{created['id']}")
    assert resp.status_code == 204
    # Verify it's gone
    get_resp = client.get(f"/api/v1/automations/{created['id']}")
    assert get_resp.status_code == 404


def test_delete_automation_removes_from_list(client: TestClient):
    agent = _create_agent(client)
    a1 = _create_automation(client, agent["id"], name="Keep")
    a2 = _create_automation(client, agent["id"], name="Remove")
    client.delete(f"/api/v1/automations/{a2['id']}")
    resp = client.get("/api/v1/automations")
    ids = [a["id"] for a in resp.json()]
    assert a1["id"] in ids
    assert a2["id"] not in ids


# ---------------------------------------------------------------------------
# POST /api/v1/automations/{id}/trigger
# ---------------------------------------------------------------------------


def test_trigger_automation_creates_run(client: TestClient, db_session: Session):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"])

    # Patch asyncio.create_task to avoid needing a real event loop in the test process.
    # trigger_automation imports asyncio locally, so we patch the top-level asyncio module.
    with patch("asyncio.create_task"):
        resp = client.post(f"/api/v1/automations/{created['id']}/trigger")

    assert resp.status_code == 200
    data = resp.json()
    assert "run" in data
    run = data["run"]
    assert run["status"] == "running"
    assert run["automation_id"] == created["id"]
    assert run["id"] is not None

    # Verify the run is in the DB
    db_run = db_session.query(AutomationRun).filter(AutomationRun.id == run["id"]).first()
    assert db_run is not None
    assert db_run.status == "running"


def test_trigger_automation_not_found(client: TestClient):
    with patch("asyncio.create_task"):
        resp = client.post("/api/v1/automations/nonexistent-id/trigger")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/automations/{id}/runs
# ---------------------------------------------------------------------------


def test_list_runs_empty(client: TestClient, db_session: Session):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"])
    resp = client.get(f"/api/v1/automations/{created['id']}/runs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_runs_returns_runs(client: TestClient, db_session: Session):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"])
    # Create runs directly via service (avoid triggering background task)
    automation_service.create_run(db_session, automation_id=created["id"])
    automation_service.create_run(db_session, automation_id=created["id"])
    db_session.commit()

    resp = client.get(f"/api/v1/automations/{created['id']}/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert len(runs) == 2
    for run in runs:
        assert run["automation_id"] == created["id"]
        assert run["status"] == "running"


def test_list_runs_pagination(client: TestClient, db_session: Session):
    agent = _create_agent(client)
    created = _create_automation(client, agent["id"])
    for _ in range(5):
        automation_service.create_run(db_session, automation_id=created["id"])
    db_session.commit()

    resp = client.get(f"/api/v1/automations/{created['id']}/runs", params={"limit": 2})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_runs_automation_not_found(client: TestClient):
    resp = client.get("/api/v1/automations/nonexistent-id/runs")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/notifications/mark-all-read
# ---------------------------------------------------------------------------


def test_mark_all_read(client: TestClient, db_session: Session):
    notification_service.create_notification(
        db_session, type="system", title="Notif 1", body="First"
    )
    notification_service.create_notification(
        db_session, type="system", title="Notif 2", body="Second"
    )
    db_session.commit()

    # Confirm both are unread before marking
    unread_before = client.get("/api/v1/notifications", params={"is_read": False})
    assert len(unread_before.json()) == 2

    resp = client.post("/api/v1/notifications/mark-all-read")
    assert resp.status_code == 200
    data = resp.json()
    assert data["marked_read"] == 2

    # Confirm both are now read
    unread_after = client.get("/api/v1/notifications", params={"is_read": False})
    assert unread_after.json() == []

    all_notifs = client.get("/api/v1/notifications")
    for notif in all_notifs.json():
        assert notif["is_read"] is True


def test_mark_all_read_no_notifications(client: TestClient):
    resp = client.post("/api/v1/notifications/mark-all-read")
    assert resp.status_code == 200
    assert resp.json()["marked_read"] == 0


def test_mark_all_read_already_read_not_double_counted(client: TestClient, db_session: Session):
    notif = notification_service.create_notification(
        db_session, type="system", title="Already Read", body="X"
    )
    db_session.commit()
    # Mark it read first
    client.post(f"/api/v1/notifications/{notif.id}/read")

    # Now create one unread
    notification_service.create_notification(
        db_session, type="system", title="New Unread", body="Y"
    )
    db_session.commit()

    resp = client.post("/api/v1/notifications/mark-all-read")
    assert resp.status_code == 200
    # Only the one previously-unread notification should be counted
    assert resp.json()["marked_read"] == 1
