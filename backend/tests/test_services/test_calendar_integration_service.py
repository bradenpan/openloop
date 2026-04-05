"""Unit tests for calendar_integration_service.

All Google Calendar API calls are mocked via unittest.mock.patch on
gcalendar_client and google_auth functions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from backend.openloop.db.models import (
    Agent,
    CalendarEvent,
    Conversation,
    ConversationSummary,
    DataSource,
    Document,
    Space,
)
from backend.openloop.services import (
    calendar_integration_service,
    data_source_service,
    space_service,
)
from contract.enums import SOURCE_TYPE_GOOGLE_CALENDAR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_space(db: Session, name: str = "Cal Space") -> Space:
    return space_service.create_space(db, name=name, template="project")


def _make_calendar_ds(db: Session, calendar_ids: list[str] | None = None) -> DataSource:
    """Create a system-level Google Calendar DataSource directly."""
    ds = data_source_service.create_data_source(
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
    return ds


def _make_event(
    db: Session,
    data_source_id: str,
    google_event_id: str = "g-ev-1",
    calendar_id: str = "primary",
    title: str = "Meeting",
    start_offset_hours: float = 1,
    duration_hours: float = 1,
    etag: str = "etag-1",
    **kwargs,
) -> CalendarEvent:
    """Insert a CalendarEvent directly into the DB."""
    now = datetime.now(UTC).replace(tzinfo=None)
    event = CalendarEvent(
        data_source_id=data_source_id,
        google_event_id=google_event_id,
        calendar_id=calendar_id,
        title=title,
        start_time=now + timedelta(hours=start_offset_hours),
        end_time=now + timedelta(hours=start_offset_hours + duration_hours),
        all_day=False,
        status="confirmed",
        etag=etag,
        synced_at=now,
        **kwargs,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _google_event(
    event_id: str = "g-ev-1",
    summary: str = "Meeting",
    start_hours_from_now: float = 1,
    duration_hours: float = 1,
    etag: str = "etag-1",
    **extra,
) -> dict:
    """Build a dict resembling a Google Calendar API event response."""
    now = datetime.now(UTC)
    start = now + timedelta(hours=start_hours_from_now)
    end = start + timedelta(hours=duration_hours)
    result = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "etag": etag,
        "status": "confirmed",
    }
    result.update(extra)
    return result


# ---------------------------------------------------------------------------
# setup_calendar
# ---------------------------------------------------------------------------


class TestSetupCalendar:
    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_creates_system_data_source(self, mock_gcal, db_session: Session):
        mock_gcal.list_events.return_value = []
        ds = calendar_integration_service.setup_calendar(db_session, calendar_ids=["primary"])
        assert ds.source_type == SOURCE_TYPE_GOOGLE_CALENDAR
        assert ds.space_id is None
        assert ds.name == "Google Calendar"
        assert ds.config["calendar_ids"] == ["primary"]

    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_idempotent_returns_existing(self, mock_gcal, db_session: Session):
        mock_gcal.list_events.return_value = []
        ds1 = calendar_integration_service.setup_calendar(db_session)
        ds2 = calendar_integration_service.setup_calendar(db_session)
        assert ds1.id == ds2.id


# ---------------------------------------------------------------------------
# sync_events
# ---------------------------------------------------------------------------


class TestSyncEvents:
    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_adds_new_events(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        mock_gcal.list_events.return_value = [
            _google_event("ev1", "Standup", 1, 0.5, "etag-a"),
            _google_event("ev2", "Lunch", 3, 1, "etag-b"),
        ]
        result = calendar_integration_service.sync_events(db_session, ds.id)
        assert result["added"] == 2
        assert result["updated"] == 0
        assert result["removed"] == 0

        cached = db_session.query(CalendarEvent).all()
        assert len(cached) == 2

    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_updates_changed_events(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        # Pre-populate a cached event
        _make_event(db_session, ds.id, "ev1", "primary", "Old Title", etag="etag-old")

        # Google returns updated version with different etag
        mock_gcal.list_events.return_value = [
            _google_event("ev1", "New Title", 1, 1, "etag-new"),
        ]
        result = calendar_integration_service.sync_events(db_session, ds.id)
        assert result["updated"] == 1
        assert result["added"] == 0

        updated = db_session.query(CalendarEvent).filter(CalendarEvent.google_event_id == "ev1").first()
        assert updated.title == "New Title"
        assert updated.etag == "etag-new"

    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_removes_deleted_events(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        # Pre-populate an event in the sync window
        _make_event(db_session, ds.id, "ev-gone", "primary", "Will be deleted", start_offset_hours=2)

        # Google returns empty list — event was deleted
        mock_gcal.list_events.return_value = []
        result = calendar_integration_service.sync_events(db_session, ds.id)
        assert result["removed"] == 1

        remaining = db_session.query(CalendarEvent).filter(CalendarEvent.google_event_id == "ev-gone").first()
        assert remaining is None

    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_skips_unchanged_events(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        _make_event(db_session, ds.id, "ev1", "primary", "Same Title", etag="same-etag")

        mock_gcal.list_events.return_value = [
            _google_event("ev1", "Same Title", 1, 1, "same-etag"),
        ]
        result = calendar_integration_service.sync_events(db_session, ds.id)
        assert result["added"] == 0
        assert result["updated"] == 0

    @patch("backend.openloop.services.calendar_integration_service.notification_service")
    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_refresh_error_creates_notification(self, mock_gcal, mock_notif, db_session: Session):
        ds = _make_calendar_ds(db_session)
        mock_gcal.list_events.side_effect = RefreshError("token expired")
        result = calendar_integration_service.sync_events(db_session, ds.id)
        assert result == {"added": 0, "updated": 0, "removed": 0}
        mock_notif.create_notification.assert_called_once()

    @patch("backend.openloop.services.calendar_integration_service.notification_service")
    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_consecutive_failures_create_notification(self, mock_gcal, mock_notif, db_session: Session):
        ds = _make_calendar_ds(db_session)
        # Build a proper HttpError with a non-401 status
        resp = MagicMock()
        resp.status = 500
        mock_gcal.list_events.side_effect = HttpError(resp, b"server error")

        # Reset failure counter for this DS
        calendar_integration_service._sync_failure_counts[ds.id] = 0

        # First 2 calls should not trigger notification
        for _ in range(2):
            calendar_integration_service.sync_events(db_session, ds.id)
        assert mock_notif.create_notification.call_count == 0

        # 3rd failure hits threshold
        calendar_integration_service.sync_events(db_session, ds.id)
        assert mock_notif.create_notification.call_count == 1

        # Clean up
        calendar_integration_service._sync_failure_counts.pop(ds.id, None)


# ---------------------------------------------------------------------------
# get_cached_events
# ---------------------------------------------------------------------------


class TestGetCachedEvents:
    def test_returns_events_in_range(self, db_session: Session):
        ds = _make_calendar_ds(db_session)
        _make_event(db_session, ds.id, "ev1", title="In range", start_offset_hours=1)
        _make_event(db_session, ds.id, "ev2", title="Also in range", start_offset_hours=2)

        now = datetime.now(UTC).replace(tzinfo=None)
        events = calendar_integration_service.get_cached_events(
            db_session, now, now + timedelta(hours=24),
        )
        assert len(events) == 2

    def test_excludes_events_outside_range(self, db_session: Session):
        ds = _make_calendar_ds(db_session)
        _make_event(db_session, ds.id, "ev-past", title="Past", start_offset_hours=-48, duration_hours=1)
        _make_event(db_session, ds.id, "ev-future", title="Future", start_offset_hours=1)

        now = datetime.now(UTC).replace(tzinfo=None)
        events = calendar_integration_service.get_cached_events(
            db_session, now, now + timedelta(hours=24),
        )
        assert len(events) == 1
        assert events[0].title == "Future"

    def test_filters_by_calendar_id(self, db_session: Session):
        ds = _make_calendar_ds(db_session)
        _make_event(db_session, ds.id, "ev1", calendar_id="primary", title="Primary")
        _make_event(db_session, ds.id, "ev2", calendar_id="work", title="Work")

        now = datetime.now(UTC).replace(tzinfo=None)
        events = calendar_integration_service.get_cached_events(
            db_session, now, now + timedelta(hours=24), calendar_id="work",
        )
        assert len(events) == 1
        assert events[0].title == "Work"


# ---------------------------------------------------------------------------
# get_upcoming_events
# ---------------------------------------------------------------------------


class TestGetUpcomingEvents:
    def test_returns_next_n_hours(self, db_session: Session):
        ds = _make_calendar_ds(db_session)
        _make_event(db_session, ds.id, "ev1", title="Soon", start_offset_hours=1)
        _make_event(db_session, ds.id, "ev2", title="Later", start_offset_hours=100)

        events = calendar_integration_service.get_upcoming_events(db_session, hours=48)
        titles = [e.title for e in events]
        assert "Soon" in titles
        assert "Later" not in titles


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------


class TestCreateEvent:
    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_creates_event_and_caches(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        now = datetime.now(UTC)
        google_resp = _google_event("new-ev", "Team Sync", 1, 1, "etag-new")
        mock_gcal.create_event.return_value = google_resp

        event = calendar_integration_service.create_event(
            db_session,
            calendar_id="primary",
            title="Team Sync",
            start=now + timedelta(hours=1),
            end=now + timedelta(hours=2),
        )
        assert event.title == "Team Sync"
        assert event.google_event_id == "new-ev"
        assert event.data_source_id == ds.id

        # Verify it was persisted
        cached = db_session.query(CalendarEvent).filter(CalendarEvent.id == event.id).first()
        assert cached is not None


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------


class TestUpdateEvent:
    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_updates_google_and_cache(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        event = _make_event(db_session, ds.id, "ev1", title="Original")

        google_resp = _google_event("ev1", "Updated Title", 1, 1, "etag-updated")
        mock_gcal.update_event.return_value = google_resp

        updated = calendar_integration_service.update_event(
            db_session, event.id, title="Updated Title",
        )
        assert updated.title == "Updated Title"
        assert updated.etag == "etag-updated"

    def test_404_for_nonexistent(self, db_session: Session):
        with pytest.raises(HTTPException) as exc_info:
            calendar_integration_service.update_event(db_session, "nonexistent-id", title="X")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# delete_event
# ---------------------------------------------------------------------------


class TestDeleteEvent:
    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_deletes_from_google_and_cache(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        event = _make_event(db_session, ds.id, "ev-del")

        calendar_integration_service.delete_event(db_session, event.id)
        mock_gcal.delete_event.assert_called_once_with("primary", "ev-del")

        remaining = db_session.query(CalendarEvent).filter(CalendarEvent.id == event.id).first()
        assert remaining is None

    def test_404_for_nonexistent(self, db_session: Session):
        with pytest.raises(HTTPException) as exc_info:
            calendar_integration_service.delete_event(db_session, "nonexistent-id")
        assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# find_free_time
# ---------------------------------------------------------------------------


class TestFindFreeTime:
    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_finds_gaps_in_busy_schedule(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        now = datetime.now(UTC)
        start = now
        end = now + timedelta(hours=8)

        # Busy from hour 1-2 and 4-5, leaving gaps: 0-1, 2-4, 5-8
        mock_gcal.find_free_busy.return_value = {
            "primary": {
                "busy": [
                    {
                        "start": (now + timedelta(hours=1)).isoformat(),
                        "end": (now + timedelta(hours=2)).isoformat(),
                    },
                    {
                        "start": (now + timedelta(hours=4)).isoformat(),
                        "end": (now + timedelta(hours=5)).isoformat(),
                    },
                ]
            }
        }

        slots = calendar_integration_service.find_free_time(
            db_session, start, end, duration_minutes=60,
        )
        assert len(slots) == 3  # 0-1, 2-4, 5-8

    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_returns_empty_when_no_ds(self, mock_gcal, db_session: Session):
        """No DataSource -> empty list."""
        now = datetime.now(UTC)
        slots = calendar_integration_service.find_free_time(
            db_session, now, now + timedelta(hours=8), duration_minutes=60,
        )
        assert slots == []

    @patch("backend.openloop.services.calendar_integration_service.gcalendar_client")
    def test_filters_by_minimum_duration(self, mock_gcal, db_session: Session):
        ds = _make_calendar_ds(db_session)
        now = datetime.now(UTC)
        start = now
        end = now + timedelta(hours=4)

        # Busy from 0:30 to 3:30 — only 30-min gap at start and 30-min gap at end
        mock_gcal.find_free_busy.return_value = {
            "primary": {
                "busy": [
                    {
                        "start": (now + timedelta(minutes=30)).isoformat(),
                        "end": (now + timedelta(hours=3, minutes=30)).isoformat(),
                    },
                ]
            }
        }

        # Need 60-min slots — neither 30-min gap qualifies
        slots = calendar_integration_service.find_free_time(
            db_session, start, end, duration_minutes=60,
        )
        assert len(slots) == 0


# ---------------------------------------------------------------------------
# get_event_with_brief
# ---------------------------------------------------------------------------


class TestGetEventWithBrief:
    def test_returns_event_data(self, db_session: Session):
        ds = _make_calendar_ds(db_session)
        event = _make_event(db_session, ds.id, "ev1", title="Project Review")

        result = calendar_integration_service.get_event_with_brief(db_session, event.id)
        assert result["id"] == event.id
        assert result["title"] == "Project Review"
        assert result["brief"] is None

    def test_returns_brief_from_document(self, db_session: Session):
        ds = _make_calendar_ds(db_session)
        event = _make_event(db_session, ds.id, "ev1", title="Budget Review")

        # Create a document with a matching title
        space = _make_space(db_session, "Doc Space")
        doc = Document(
            space_id=space.id,
            title="Budget Review Notes",
            source="manual",
        )
        db_session.add(doc)
        db_session.commit()
        db_session.refresh(doc)

        result = calendar_integration_service.get_event_with_brief(db_session, event.id)
        assert result["brief"] is not None
        assert result["brief"]["type"] == "document"
        assert result["brief"]["id"] == doc.id

    def test_404_for_nonexistent(self, db_session: Session):
        with pytest.raises(HTTPException) as exc_info:
            calendar_integration_service.get_event_with_brief(db_session, "nonexistent-id")
        assert exc_info.value.status_code == 404
