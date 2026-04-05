from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = [
    "CalendarEventCreate",
    "CalendarEventUpdate",
    "CalendarEventResponse",
    "CalendarSyncResponse",
    "CalendarAuthStatusResponse",
    "FreeTimeSlot",
    "CalendarSetupRequest",
]


class CalendarEventCreate(BaseModel):
    calendar_id: str = "primary"
    title: str
    start: str
    end: str
    description: str | None = None
    location: str | None = None
    attendees: list[str] | None = None


class CalendarEventUpdate(BaseModel):
    title: str | None = None
    start: str | None = None
    end: str | None = None
    description: str | None = None
    location: str | None = None
    attendees: list[str] | None = None


class CalendarEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    data_source_id: str | None
    google_event_id: str | None
    calendar_id: str
    title: str
    description: str | None
    location: str | None
    start_time: datetime
    end_time: datetime
    all_day: bool
    attendees: list | None
    organizer: dict | None
    conference_data: dict | None
    status: str
    recurrence_rule: str | None
    html_link: str | None
    etag: str | None
    synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
    brief: dict | None = None


class CalendarSyncResponse(BaseModel):
    added: int
    updated: int
    removed: int


class CalendarAuthStatusResponse(BaseModel):
    authenticated: bool
    has_calendar_scopes: bool


class FreeTimeSlot(BaseModel):
    start: str
    end: str


class CalendarSetupRequest(BaseModel):
    calendar_ids: list[str] | None = None
