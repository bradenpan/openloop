from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.services import notification_service


def _make_notification(db: Session, title: str = "Test Notif") -> str:
    """Create a notification directly via service and return its id."""
    notif = notification_service.create_notification(
        db, type="system", title=title, body="Body text"
    )
    return notif.id


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_notifications_empty(client: TestClient):
    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_notifications(client: TestClient, db_session: Session):
    _make_notification(db_session, "N1")
    _make_notification(db_session, "N2")
    resp = client.get("/api/v1/notifications")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_notifications_filter_unread(client: TestClient, db_session: Session):
    nid = _make_notification(db_session, "Read Me")
    _make_notification(db_session, "Unread")
    # Mark one as read
    client.post(f"/api/v1/notifications/{nid}/read")
    resp = client.get("/api/v1/notifications", params={"is_read": False})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Unread"


# ---------------------------------------------------------------------------
# Mark read
# ---------------------------------------------------------------------------


def test_mark_read(client: TestClient, db_session: Session):
    nid = _make_notification(db_session, "Mark Me")
    resp = client.post(f"/api/v1/notifications/{nid}/read")
    assert resp.status_code == 200
    assert resp.json()["is_read"] is True


def test_mark_read_not_found(client: TestClient):
    resp = client.post("/api/v1/notifications/nonexistent/read")
    assert resp.status_code == 404
