from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from backend.openloop.api.schemas import DataSourceResponse
from backend.openloop.api.schemas.calendar import (
    CalendarAuthStatusResponse,
    CalendarEventCreate,
    CalendarEventResponse,
    CalendarEventUpdate,
    CalendarSetupRequest,
    CalendarSyncResponse,
    FreeTimeSlot,
)
from backend.openloop.database import get_db
from backend.openloop.db.models import DataSource
from backend.openloop.services import calendar_integration_service, gcalendar_client, google_auth
from contract.enums import SOURCE_TYPE_GOOGLE_CALENDAR

router = APIRouter(prefix="/api/v1/calendar", tags=["calendar"])


@router.get("/auth-status", response_model=CalendarAuthStatusResponse)
def get_auth_status() -> CalendarAuthStatusResponse:
    authenticated = google_auth.is_authenticated()
    has_calendar_scopes = gcalendar_client.is_authenticated()
    return CalendarAuthStatusResponse(
        authenticated=authenticated,
        has_calendar_scopes=has_calendar_scopes,
    )


@router.get("/events", response_model=list[CalendarEventResponse])
def list_events(
    start: str | None = Query(None),
    end: str | None = Query(None),
    calendar_id: str | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> list[CalendarEventResponse]:
    now = datetime.now(UTC).replace(tzinfo=None)
    try:
        if start:
            start_dt = datetime.fromisoformat(start).replace(tzinfo=None)
        else:
            start_dt = now
        if end:
            end_dt = datetime.fromisoformat(end).replace(tzinfo=None)
        else:
            end_dt = now + timedelta(days=7)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format for start or end")

    events = calendar_integration_service.get_cached_events(
        db, start=start_dt, end=end_dt, calendar_id=calendar_id
    )
    page = events[offset : offset + limit]
    return [CalendarEventResponse.model_validate(e) for e in page]


@router.get("/events/{event_id}")
def get_event(event_id: str, db: Session = Depends(get_db)) -> dict:
    return calendar_integration_service.get_event_with_brief(db, event_id)


@router.post("/events", response_model=CalendarEventResponse, status_code=201)
def create_event(
    body: CalendarEventCreate, db: Session = Depends(get_db)
) -> CalendarEventResponse:
    kwargs: dict = {}
    if body.description is not None:
        kwargs["description"] = body.description
    if body.location is not None:
        kwargs["location"] = body.location
    if body.attendees is not None:
        kwargs["attendees"] = [{"email": e} for e in body.attendees]

    try:
        start_dt = datetime.fromisoformat(body.start).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(body.end).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format for start or end")

    event = calendar_integration_service.create_event(
        db,
        calendar_id=body.calendar_id,
        title=body.title,
        start=start_dt,
        end=end_dt,
        **kwargs,
    )
    return CalendarEventResponse.model_validate(event)


@router.patch("/events/{event_id}", response_model=CalendarEventResponse)
def update_event(
    event_id: str, body: CalendarEventUpdate, db: Session = Depends(get_db)
) -> CalendarEventResponse:
    updates = body.model_dump(exclude_unset=True)

    # Convert ISO string dates to datetime objects for the service
    try:
        if "start" in updates:
            updates["start"] = datetime.fromisoformat(updates["start"]).replace(tzinfo=None)
        if "end" in updates:
            updates["end"] = datetime.fromisoformat(updates["end"]).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format for start or end")
    # Convert attendees list[str] to list[dict]
    if "attendees" in updates and updates["attendees"] is not None:
        updates["attendees"] = [{"email": e} for e in updates["attendees"]]

    event = calendar_integration_service.update_event(db, event_id, **updates)
    return CalendarEventResponse.model_validate(event)


@router.delete("/events/{event_id}", status_code=204)
def delete_event(event_id: str, db: Session = Depends(get_db)) -> None:
    calendar_integration_service.delete_event(db, event_id)


@router.post("/sync", response_model=CalendarSyncResponse)
def sync_events(db: Session = Depends(get_db)) -> CalendarSyncResponse:
    ds = (
        db.query(DataSource)
        .filter(
            DataSource.source_type == SOURCE_TYPE_GOOGLE_CALENDAR,
            DataSource.space_id.is_(None),
        )
        .first()
    )
    if not ds:
        raise HTTPException(status_code=404, detail="No Google Calendar data source found")
    result = calendar_integration_service.sync_events(db, ds.id)
    return CalendarSyncResponse(**result)


@router.get("/free-time", response_model=list[FreeTimeSlot])
def get_free_time(
    start: str = Query(...),
    end: str = Query(...),
    duration_minutes: int = Query(...),
    db: Session = Depends(get_db),
) -> list[FreeTimeSlot]:
    try:
        start_dt = datetime.fromisoformat(start).replace(tzinfo=None)
        end_dt = datetime.fromisoformat(end).replace(tzinfo=None)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid datetime format for start or end")
    slots = calendar_integration_service.find_free_time(
        db, start=start_dt, end=end_dt, duration_minutes=duration_minutes
    )
    return [FreeTimeSlot(**s) for s in slots]


@router.get("/calendars")
def list_calendars() -> list[dict]:
    return gcalendar_client.list_calendars()


@router.post("/setup", response_model=DataSourceResponse, status_code=201)
def setup_calendar(
    body: CalendarSetupRequest, db: Session = Depends(get_db)
) -> DataSourceResponse:
    ds = calendar_integration_service.setup_calendar(db, calendar_ids=body.calendar_ids)
    return DataSourceResponse.model_validate(ds)
