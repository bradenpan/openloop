"""API tests for calendar endpoints.

All Google Calendar API and auth calls are mocked to avoid real HTTP.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.db.models import CalendarEvent, DataSource
from backend.openloop.services import data_source_service
from contract.enums import SOURCE_TYPE_GOOGLE_CALENDAR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_calendar_ds(db: Session, calendar_ids: list[str] | None = None) -> DataSource:
    """Create a system-level Google Calendar DataSource directly in the DB."""
    return data_source_service.create_data_source(
        db,
        space_id=None,
        name="Google Calendar",
        source_type=SOURCE_TYPE_GOOGLE_CALENDAR,
        config={
            "calendar_ids": calendar_ids or ["primary"],
            "sync_window_days": 30,
            "default_calendar_id": "primary",
        },
    )


def _make_event(
    db: Session,
    data_source_id: str,
    google_event_id: str = "g-ev-1",
    title: str = "Meeting",
    start_offset_hours: float = 1,
    duration_hours: float = 1,
) -> CalendarEvent:
    now = datetime.now(UTC).replace(tzinfo=None)
    event = CalendarEvent(
        data_source_id=data_source_id,
        google_event_id=google_event_id,
        calendar_id="primary",
        title=title,
        start_time=now + timedelta(hours=start_offset_hours),
        end_time=now + timedelta(hours=start_offset_hours + duration_hours),
        all_day=False,
        status="confirmed",
        etag="etag-1",
        synced_at=now,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _google_event_response(
    event_id: str = "g-ev-new",
    summary: str = "New Event",
) -> dict:
    now = datetime.now(UTC)
    start = now + timedelta(hours=1)
    end = start + timedelta(hours=1)
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "etag": "etag-new",
        "status": "confirmed",
    }


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/auth-status
# ---------------------------------------------------------------------------


@patch("backend.openloop.api.routes.calendar.gcalendar_client")
@patch("backend.openloop.api.routes.calendar.google_auth")
def test_auth_status(mock_auth, mock_gcal, client: TestClient):
    mock_auth.is_authenticated.return_value = True
    mock_gcal.is_authenticated.return_value = True
    resp = client.get("/api/v1/calendar/auth-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is True
    assert data["has_calendar_scopes"] is True


@patch("backend.openloop.api.routes.calendar.gcalendar_client")
@patch("backend.openloop.api.routes.calendar.google_auth")
def test_auth_status_not_authenticated(mock_auth, mock_gcal, client: TestClient):
    mock_auth.is_authenticated.return_value = False
    mock_gcal.is_authenticated.return_value = False
    resp = client.get("/api/v1/calendar/auth-status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is False
    assert data["has_calendar_scopes"] is False


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/events
# ---------------------------------------------------------------------------


def test_list_events(client: TestClient, db_session: Session):
    ds = _make_calendar_ds(db_session)
    _make_event(db_session, ds.id, "ev1", "Standup", start_offset_hours=1)
    _make_event(db_session, ds.id, "ev2", "Design Review", start_offset_hours=2)

    resp = client.get("/api/v1/calendar/events")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


def test_list_events_pagination(client: TestClient, db_session: Session):
    ds = _make_calendar_ds(db_session)
    for i in range(5):
        _make_event(db_session, ds.id, f"ev{i}", f"Event {i}", start_offset_hours=i + 1)

    resp = client.get("/api/v1/calendar/events", params={"limit": 2, "offset": 0})
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_events_empty(client: TestClient, db_session: Session):
    resp = client.get("/api/v1/calendar/events")
    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/events/{id}
# ---------------------------------------------------------------------------


def test_get_event(client: TestClient, db_session: Session):
    ds = _make_calendar_ds(db_session)
    event = _make_event(db_session, ds.id, "ev1", "Team Meeting")

    resp = client.get(f"/api/v1/calendar/events/{event.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == event.id
    assert data["title"] == "Team Meeting"


def test_get_event_not_found(client: TestClient):
    resp = client.get("/api/v1/calendar/events/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/events
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
def test_create_event(mock_gcal, client: TestClient, db_session: Session):
    _make_calendar_ds(db_session)
    mock_gcal.create_event.return_value = _google_event_response("created-ev", "Sprint Planning")

    now = datetime.now(UTC)
    resp = client.post(
        "/api/v1/calendar/events",
        json={
            "calendar_id": "primary",
            "title": "Sprint Planning",
            "start": (now + timedelta(hours=1)).isoformat(),
            "end": (now + timedelta(hours=2)).isoformat(),
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Sprint Planning"
    assert data["google_event_id"] == "created-ev"


# ---------------------------------------------------------------------------
# PATCH /api/v1/calendar/events/{id}
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
def test_update_event(mock_gcal, client: TestClient, db_session: Session):
    ds = _make_calendar_ds(db_session)
    event = _make_event(db_session, ds.id, "ev1", "Old Name")

    mock_gcal.update_event.return_value = _google_event_response("ev1", "New Name")

    resp = client.patch(
        f"/api/v1/calendar/events/{event.id}",
        json={"title": "New Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "New Name"


def test_update_event_not_found(client: TestClient):
    resp = client.patch(
        "/api/v1/calendar/events/nonexistent-id",
        json={"title": "X"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/v1/calendar/events/{id}
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
def test_delete_event(mock_gcal, client: TestClient, db_session: Session):
    ds = _make_calendar_ds(db_session)
    event = _make_event(db_session, ds.id, "ev-del", "To Delete")

    resp = client.delete(f"/api/v1/calendar/events/{event.id}")
    assert resp.status_code == 204
    mock_gcal.delete_event.assert_called_once()


def test_delete_event_not_found(client: TestClient):
    resp = client.delete("/api/v1/calendar/events/nonexistent-id")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/sync
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
def test_sync_events(mock_gcal, client: TestClient, db_session: Session):
    ds = _make_calendar_ds(db_session)
    mock_gcal.list_events.return_value = [
        _google_event_response("sync-ev", "Synced Meeting"),
    ]
    resp = client.post("/api/v1/calendar/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert "added" in data
    assert "updated" in data
    assert "removed" in data


def test_sync_events_no_ds(client: TestClient):
    """Sync when no DataSource exists should return 404."""
    resp = client.post("/api/v1/calendar/sync")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/free-time
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
def test_free_time(mock_gcal, client: TestClient, db_session: Session):
    _make_calendar_ds(db_session)
    now = datetime.now(UTC)

    mock_gcal.find_free_busy.return_value = {
        "primary": {"busy": []},
    }

    resp = client.get(
        "/api/v1/calendar/free-time",
        params={
            "start": now.isoformat(),
            "end": (now + timedelta(hours=8)).isoformat(),
            "duration_minutes": 30,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    # No busy periods -> one big free slot
    assert len(data) == 1


# ---------------------------------------------------------------------------
# GET /api/v1/calendar/calendars
# ---------------------------------------------------------------------------


@patch("backend.openloop.api.routes.calendar.gcalendar_client")
def test_list_calendars(mock_gcal, client: TestClient):
    mock_gcal.list_calendars.return_value = [
        {"id": "primary", "summary": "My Calendar", "primary": True},
        {"id": "work@group.v.calendar.google.com", "summary": "Work"},
    ]
    resp = client.get("/api/v1/calendar/calendars")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


# ---------------------------------------------------------------------------
# POST /api/v1/calendar/setup
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
def test_setup_calendar(mock_gcal, client: TestClient, db_session: Session):
    mock_gcal.list_events.return_value = []
    resp = client.post(
        "/api/v1/calendar/setup",
        json={"calendar_ids": ["primary"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_type"] == SOURCE_TYPE_GOOGLE_CALENDAR
    assert data["space_id"] is None


@patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
def test_setup_calendar_idempotent(mock_gcal, client: TestClient, db_session: Session):
    mock_gcal.list_events.return_value = []
    resp1 = client.post("/api/v1/calendar/setup", json={})
    resp2 = client.post("/api/v1/calendar/setup", json={})
    assert resp1.status_code == 201
    assert resp2.status_code == 201
    assert resp1.json()["id"] == resp2.json()["id"]
