"""Calendar integration service — sync, CRUD, and free time calculation."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from backend.openloop.db.models import CalendarEvent, ConversationSummary, DataSource, Document
from backend.openloop.services import data_source_service, gcalendar_client, notification_service
from contract.enums import SOURCE_TYPE_GOOGLE_CALENDAR, NotificationType

logger = logging.getLogger(__name__)


def _parse_iso(s: str) -> datetime:
    """Parse an ISO 8601 string, handling Google's 'Z' suffix."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _escape_like(term: str) -> str:
    """Escape SQL LIKE wildcards."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


# Track consecutive sync failures per data source
_sync_failure_counts: dict[str, int] = {}
_FAILURE_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------


def setup_calendar(
    db: Session,
    calendar_ids: list[str] | None = None,
) -> DataSource:
    """Create a system DataSource for Google Calendar (idempotent) and run initial sync."""
    # Check if a system-level Google Calendar DataSource already exists
    existing = (
        db.query(DataSource)
        .filter(
            DataSource.source_type == SOURCE_TYPE_GOOGLE_CALENDAR,
            DataSource.space_id.is_(None),
        )
        .first()
    )
    if existing:
        return existing

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

    # Run initial sync
    sync_events(db, ds.id)
    return ds


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


def sync_events(db: Session, data_source_id: str) -> dict:
    """Sync events from Google Calendar API into the local cache.

    Returns counts: ``{"added": N, "updated": N, "removed": N}``.
    """
    ds = data_source_service.get_data_source(db, data_source_id)
    config = ds.config or {}
    calendar_ids = config.get("calendar_ids", ["primary"])
    sync_window_days = config.get("sync_window_days", 30)

    now = datetime.now(UTC)
    time_min = (now - timedelta(days=7)).isoformat()
    time_max = (now + timedelta(days=sync_window_days)).isoformat()

    added = 0
    updated = 0
    removed = 0

    for cal_id in calendar_ids:
        try:
            google_events = gcalendar_client.list_events(
                calendar_id=cal_id,
                time_min=time_min,
                time_max=time_max,
            )
        except RefreshError:
            logger.error("Google Calendar token expired for data_source %s", data_source_id)
            notification_service.create_notification(
                db,
                type=NotificationType.SYSTEM,
                title="Google Calendar disconnected",
                body="Google Calendar authentication has expired — re-authentication needed.",
            )
            return {"added": 0, "updated": 0, "removed": 0}
        except HttpError as exc:
            if exc.resp.status == 401:
                logger.error("Google Calendar 401 for data_source %s", data_source_id)
                notification_service.create_notification(
                    db,
                    type=NotificationType.SYSTEM,
                    title="Google Calendar disconnected",
                    body="Google Calendar authentication has expired — re-authentication needed.",
                )
                return {"added": 0, "updated": 0, "removed": 0}

            # Other API error — increment failure counter
            _sync_failure_counts[data_source_id] = _sync_failure_counts.get(data_source_id, 0) + 1
            if _sync_failure_counts[data_source_id] >= _FAILURE_THRESHOLD:
                notification_service.create_notification(
                    db,
                    type=NotificationType.SYSTEM,
                    title="Calendar sync failed",
                    body="Calendar sync has failed 3 consecutive times — check Google auth.",
                )
            logger.error("Google Calendar API error for data_source %s: %s", data_source_id, exc)
            return {"added": 0, "updated": 0, "removed": 0}

        # Build a set of google_event_ids we saw in this response
        seen_google_ids: set[str] = set()

        for g_event in google_events:
            g_id = g_event.get("id")
            if not g_id:
                continue
            seen_google_ids.add(g_id)

            mapped = _map_google_event(g_event, cal_id)

            existing = (
                db.query(CalendarEvent)
                .filter(CalendarEvent.google_event_id == g_id)
                .first()
            )

            if existing is None:
                # INSERT
                event = CalendarEvent(data_source_id=data_source_id, **mapped)
                db.add(event)
                added += 1
            elif existing.etag != mapped.get("etag"):
                # UPDATE — etag differs
                for key, value in mapped.items():
                    setattr(existing, key, value)
                updated += 1
            # else: etag matches, skip

        # Detect deletions: cached events in the time window for this cal_id
        # that were NOT returned by Google
        # Use naive datetimes for the comparison (SQLite stores naive)
        window_start = (now - timedelta(days=7)).replace(tzinfo=None)
        window_end = (now + timedelta(days=sync_window_days)).replace(tzinfo=None)

        cached_in_window = (
            db.query(CalendarEvent)
            .filter(
                CalendarEvent.calendar_id == cal_id,
                CalendarEvent.data_source_id == data_source_id,
                CalendarEvent.start_time < window_end,
                CalendarEvent.end_time > window_start,
            )
            .all()
        )

        for cached_event in cached_in_window:
            if cached_event.google_event_id and cached_event.google_event_id not in seen_google_ids:
                db.delete(cached_event)
                removed += 1

        db.commit()

    # Success — reset failure count
    _sync_failure_counts[data_source_id] = 0

    return {"added": added, "updated": updated, "removed": removed}


def _map_google_event(event: dict, calendar_id: str) -> dict:
    """Map a Google Calendar API event dict to CalendarEvent fields."""
    start = event.get("start", {})
    end = event.get("end", {})

    # Handle all-day events (date) vs timed events (dateTime)
    all_day = "date" in start
    if all_day:
        start_time = _parse_iso(start["date"])
        # Google uses exclusive end date for all-day events; subtract 1 second for inclusive
        end_time = _parse_iso(end["date"]) - timedelta(seconds=1)
    else:
        start_time = _parse_iso(start.get("dateTime", ""))
        end_time = _parse_iso(end.get("dateTime", ""))

    return {
        "google_event_id": event["id"],
        "calendar_id": calendar_id,
        "title": event.get("summary", "(No title)"),
        "description": event.get("description"),
        "location": event.get("location"),
        "start_time": start_time,
        "end_time": end_time,
        "all_day": all_day,
        "attendees": event.get("attendees"),
        "organizer": event.get("organizer"),
        "conference_data": event.get("conferenceData"),
        "status": event.get("status", "confirmed"),
        "recurrence_rule": (event.get("recurrence") or [None])[0],
        "html_link": event.get("htmlLink"),
        "etag": event.get("etag"),
        "synced_at": datetime.now(UTC).replace(tzinfo=None),
    }


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def get_cached_events(
    db: Session,
    start: datetime,
    end: datetime,
    calendar_id: str | None = None,
) -> list[CalendarEvent]:
    """Return cached CalendarEvents within the given time range."""
    query = db.query(CalendarEvent).filter(
        CalendarEvent.start_time >= start,
        CalendarEvent.end_time <= end,
    )
    if calendar_id:
        query = query.filter(CalendarEvent.calendar_id == calendar_id)
    return query.order_by(CalendarEvent.start_time.asc()).all()


def get_upcoming_events(
    db: Session,
    hours: int = 48,
) -> list[CalendarEvent]:
    """Convenience: return cached events for the next *hours* hours."""
    now = datetime.now(UTC).replace(tzinfo=None)
    end = now + timedelta(hours=hours)
    return get_cached_events(db, now, end)


# ---------------------------------------------------------------------------
# CRUD (write-through: Google API first, then local cache)
# ---------------------------------------------------------------------------


def create_event(
    db: Session,
    calendar_id: str,
    title: str,
    start: datetime,
    end: datetime,
    **kwargs,
) -> CalendarEvent:
    """Create an event on Google Calendar and cache it locally."""
    # Build Google event body
    event_body: dict = {
        "summary": title,
        "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
    }
    if kwargs.get("description"):
        event_body["description"] = kwargs["description"]
    if kwargs.get("location"):
        event_body["location"] = kwargs["location"]
    if kwargs.get("attendees"):
        event_body["attendees"] = kwargs["attendees"]

    # Create in Google
    google_response = gcalendar_client.create_event(calendar_id, event_body)

    # Map response to CalendarEvent fields
    mapped = _map_google_event(google_response, calendar_id)

    # Get the calendar DataSource
    calendar_ds = (
        db.query(DataSource)
        .filter(
            DataSource.source_type == SOURCE_TYPE_GOOGLE_CALENDAR,
            DataSource.space_id.is_(None),
        )
        .first()
    )

    event = CalendarEvent(
        data_source_id=calendar_ds.id if calendar_ds else None,
        **mapped,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def update_event(db: Session, event_id: str, **kwargs) -> CalendarEvent:
    """Update a cached calendar event on Google and refresh the local cache."""
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Calendar event not found")

    # Build partial update body for Google API
    update_body: dict = {}
    if "title" in kwargs:
        update_body["summary"] = kwargs["title"]
    if "description" in kwargs:
        update_body["description"] = kwargs["description"]
    if "location" in kwargs:
        update_body["location"] = kwargs["location"]
    if "start" in kwargs:
        update_body["start"] = {"dateTime": kwargs["start"].isoformat(), "timeZone": "UTC"}
    if "end" in kwargs:
        update_body["end"] = {"dateTime": kwargs["end"].isoformat(), "timeZone": "UTC"}
    if "attendees" in kwargs:
        update_body["attendees"] = kwargs["attendees"]

    # Update in Google with etag for conflict detection
    google_response = gcalendar_client.update_event(
        event.calendar_id,
        event.google_event_id,
        update_body,
        etag=event.etag,
    )

    # Update local cache from Google's response
    mapped = _map_google_event(google_response, event.calendar_id)
    for key, value in mapped.items():
        setattr(event, key, value)

    db.commit()
    db.refresh(event)
    return event


def delete_event(db: Session, event_id: str) -> None:
    """Delete a calendar event from Google and remove from local cache."""
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Calendar event not found")

    gcalendar_client.delete_event(event.calendar_id, event.google_event_id)
    db.delete(event)
    db.commit()


# ---------------------------------------------------------------------------
# Free time calculation
# ---------------------------------------------------------------------------


def find_free_time(
    db: Session,
    start: datetime,
    end: datetime,
    duration_minutes: int,
) -> list[dict]:
    """Find available time slots of at least *duration_minutes* between *start* and *end*.

    Uses Google Calendar's freebusy API.
    """
    # Get calendar IDs from the DataSource config
    calendar_ds = (
        db.query(DataSource)
        .filter(
            DataSource.source_type == SOURCE_TYPE_GOOGLE_CALENDAR,
            DataSource.space_id.is_(None),
        )
        .first()
    )
    if not calendar_ds:
        return []

    config = calendar_ds.config or {}
    calendar_ids = config.get("calendar_ids", ["primary"])

    time_min = start.isoformat()
    time_max = end.isoformat()

    freebusy_result = gcalendar_client.find_free_busy(calendar_ids, time_min, time_max)

    # Merge all busy periods across calendars
    busy_periods: list[tuple[datetime, datetime]] = []
    for _cal_id, cal_data in freebusy_result.items():
        for busy in cal_data.get("busy", []):
            busy_start = _parse_iso(busy["start"])
            busy_end = _parse_iso(busy["end"])
            busy_periods.append((busy_start, busy_end))

    # Sort busy periods by start time
    busy_periods.sort(key=lambda x: x[0])

    # Merge overlapping busy periods
    merged: list[tuple[datetime, datetime]] = []
    for b_start, b_end in busy_periods:
        if merged and b_start <= merged[-1][1]:
            # Overlapping — extend the end
            merged[-1] = (merged[-1][0], max(merged[-1][1], b_end))
        else:
            merged.append((b_start, b_end))

    # Find gaps >= duration_minutes
    required = timedelta(minutes=duration_minutes)
    slots: list[dict] = []
    cursor = start

    for b_start, b_end in merged:
        if b_start > cursor:
            gap = b_start - cursor
            if gap >= required:
                slots.append({
                    "start": cursor.isoformat(),
                    "end": b_start.isoformat(),
                })
        cursor = max(cursor, b_end)

    # Check trailing gap after last busy period
    if end > cursor:
        gap = end - cursor
        if gap >= required:
            slots.append({
                "start": cursor.isoformat(),
                "end": end.isoformat(),
            })

    return slots


# ---------------------------------------------------------------------------
# Event + brief lookup
# ---------------------------------------------------------------------------


def get_event_with_brief(db: Session, event_id: str) -> dict:
    """Return a calendar event plus any related meeting brief (conversation or document)."""
    event = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Calendar event not found")

    brief: dict | None = None
    search_terms = [event.title]

    # Also search for attendee names if attendees exist
    if event.attendees:
        for attendee in event.attendees:
            name = attendee.get("displayName")
            if name:
                search_terms.append(name)

    for term in search_terms:
        if brief:
            break

        # Search ConversationSummary
        summary = (
            db.query(ConversationSummary)
            .filter(ConversationSummary.summary.ilike(f"%{_escape_like(term)}%", escape="\\"))
            .order_by(ConversationSummary.created_at.desc())
            .first()
        )
        if summary:
            brief = {
                "type": "conversation",
                "id": summary.id,
                "title": summary.summary[:120],
            }
            break

        # Search Document
        doc = (
            db.query(Document)
            .filter(Document.title.ilike(f"%{_escape_like(term)}%", escape="\\"))
            .order_by(Document.created_at.desc())
            .first()
        )
        if doc:
            brief = {
                "type": "document",
                "id": doc.id,
                "title": doc.title,
            }
            break

    result = {
        "id": event.id,
        "google_event_id": event.google_event_id,
        "calendar_id": event.calendar_id,
        "title": event.title,
        "description": event.description,
        "location": event.location,
        "start_time": event.start_time.isoformat() if event.start_time else None,
        "end_time": event.end_time.isoformat() if event.end_time else None,
        "all_day": event.all_day,
        "attendees": event.attendees,
        "organizer": event.organizer,
        "conference_data": event.conference_data,
        "status": event.status,
        "html_link": event.html_link,
        "brief": brief,
    }
    return result
