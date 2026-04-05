"""Google Calendar API client for OpenLoop."""

from __future__ import annotations

import logging
import time

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.openloop.services import google_auth

logger = logging.getLogger(__name__)

# Register calendar scopes on import
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]
google_auth.register_scopes("calendar", SCOPES)


def is_authenticated() -> bool:
    """Check if Google Calendar scopes are granted."""
    return google_auth.is_authenticated(SCOPES)


def get_calendar_service():
    """Build and return a Google Calendar API service resource."""
    creds = google_auth.get_credentials()
    if creds is None:
        raise RuntimeError(
            "Google Calendar not authenticated. Complete OAuth flow first."
        )
    # Check that calendar scopes are granted
    granted = set(creds.scopes or [])
    if not all(s in granted for s in SCOPES):
        raise RuntimeError(
            "Calendar scopes not granted. Re-authenticate with calendar scopes."
        )
    return build("calendar", "v3", credentials=creds)


def _retry_api_call(func, max_retries: int = 3):
    """Wrap Google API calls with exponential backoff for 429 and 5xx errors."""
    for attempt in range(max_retries):
        try:
            return func()
        except HttpError as e:
            if e.resp.status in (429, 500, 502, 503) and attempt < max_retries - 1:
                wait = (2 ** attempt) + (time.time() % 1)  # jittered backoff
                logger.warning(
                    "Google API error %s, retrying in %.1fs", e.resp.status, wait
                )
                time.sleep(wait)
            else:
                raise


def list_calendars() -> list[dict]:
    """List all calendars the user has access to."""
    service = get_calendar_service()
    result = _retry_api_call(lambda: service.calendarList().list().execute())
    return result.get("items", [])


def list_events(
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 250,
) -> list[dict]:
    """List events in date range. Expands recurring events into individual instances."""
    service = get_calendar_service()

    kwargs: dict = {
        "calendarId": calendar_id,
        "singleEvents": True,  # Expand recurring events
        "orderBy": "startTime",
        "maxResults": min(max_results, 2500),
    }
    if time_min:
        kwargs["timeMin"] = time_min
    if time_max:
        kwargs["timeMax"] = time_max

    all_events: list[dict] = []
    page_token = None

    while True:
        if page_token:
            kwargs["pageToken"] = page_token

        result = _retry_api_call(
            lambda: service.events().list(**kwargs).execute()
        )
        all_events.extend(result.get("items", []))

        page_token = result.get("nextPageToken")
        if not page_token or len(all_events) >= max_results:
            break

    return all_events[:max_results]


def get_event(calendar_id: str, event_id: str) -> dict:
    """Get single event detail."""
    service = get_calendar_service()
    return _retry_api_call(
        lambda: service.events()
        .get(calendarId=calendar_id, eventId=event_id)
        .execute()
    )


def create_event(calendar_id: str, event_body: dict) -> dict:
    """Create event. If attendees included, sends invite emails."""
    service = get_calendar_service()
    send_updates = "all" if event_body.get("attendees") else "none"
    return _retry_api_call(
        lambda: service.events()
        .insert(
            calendarId=calendar_id,
            body=event_body,
            sendUpdates=send_updates,
        )
        .execute()
    )


def update_event(
    calendar_id: str,
    event_id: str,
    event_body: dict,
    etag: str | None = None,
) -> dict:
    """Update event fields. Uses etag for conflict detection (412 on stale)."""
    service = get_calendar_service()

    send_updates = "all" if event_body.get("attendees") else "none"

    def _do_patch():
        request = service.events().patch(
            calendarId=calendar_id,
            eventId=event_id,
            body=event_body,
            sendUpdates=send_updates,
        )
        if etag:
            request.headers["If-Match"] = etag
        return request.execute()

    return _retry_api_call(_do_patch)


def delete_event(calendar_id: str, event_id: str) -> None:
    """Delete/cancel event."""
    service = get_calendar_service()
    _retry_api_call(
        lambda: service.events()
        .delete(
            calendarId=calendar_id,
            eventId=event_id,
            sendUpdates="all",
        )
        .execute()
    )


def find_free_busy(
    calendar_ids: list[str],
    time_min: str,
    time_max: str,
) -> dict:
    """Free/busy query across calendars."""
    service = get_calendar_service()
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": cal_id} for cal_id in calendar_ids],
    }
    result = _retry_api_call(
        lambda: service.freebusy().query(body=body).execute()
    )
    return result.get("calendars", {})
