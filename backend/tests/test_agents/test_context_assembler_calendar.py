"""Tests for _build_calendar_section in the Context Assembler module (Fix R7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import insert
from sqlalchemy.orm import Session

from backend.openloop.agents.context_assembler import _build_calendar_section
from backend.openloop.db.models import CalendarEvent, DataSource, Space, space_data_source_exclusions
from contract.enums import SOURCE_TYPE_GOOGLE_CALENDAR


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_calendar_datasource(db: Session) -> DataSource:
    """Create a system-level Google Calendar DataSource (space_id=None)."""
    ds = DataSource(
        space_id=None,
        name="Google Calendar",
        source_type=SOURCE_TYPE_GOOGLE_CALENDAR,
        config={"calendar_ids": ["primary"]},
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    return ds


def _make_space(db: Session, name: str = "Test Space") -> Space:
    space = Space(name=name, template="project")
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


def _make_event(
    db: Session,
    data_source_id: str,
    title: str,
    start_time: datetime,
    end_time: datetime | None = None,
    *,
    all_day: bool = False,
    attendees: list | None = None,
    conference_data: dict | None = None,
) -> CalendarEvent:
    """Create a CalendarEvent in the test DB."""
    if end_time is None:
        end_time = start_time + timedelta(hours=1)
    event = CalendarEvent(
        data_source_id=data_source_id,
        calendar_id="primary",
        title=title,
        start_time=start_time.replace(tzinfo=None),
        end_time=end_time.replace(tzinfo=None),
        all_day=all_day,
        attendees=attendees,
        conference_data=conference_data,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _exclude_datasource_from_space(db: Session, space_id: str, ds_id: str) -> None:
    """Add an exclusion row so the DataSource is hidden from the given space."""
    db.execute(
        insert(space_data_source_exclusions).values(
            space_id=space_id,
            data_source_id=ds_id,
        )
    )
    db.commit()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_calendar_section_returns_empty_when_no_datasource(db_session: Session):
    """No Google Calendar DataSource exists -> returns empty string."""
    result = _build_calendar_section(db_session, space_id=None)
    assert result == ""


def test_calendar_section_returns_events_when_datasource_exists(db_session: Session):
    """DataSource + events in next 48h -> returns non-empty string with event titles."""
    ds = _make_calendar_datasource(db_session)
    now = datetime.now(UTC)

    _make_event(db_session, ds.id, "Team Standup", now + timedelta(hours=2))
    _make_event(db_session, ds.id, "Design Review", now + timedelta(hours=5))

    result = _build_calendar_section(db_session, space_id=None)
    assert result != ""
    assert "Team Standup" in result
    assert "Design Review" in result
    assert "Upcoming Calendar" in result


def test_calendar_section_excluded_for_space(db_session: Session):
    """DataSource excluded from a space -> calling with that space_id returns empty."""
    ds = _make_calendar_datasource(db_session)
    space = _make_space(db_session, name="Excluded Space")
    now = datetime.now(UTC)

    _make_event(db_session, ds.id, "Meeting", now + timedelta(hours=3))
    _exclude_datasource_from_space(db_session, space.id, ds.id)

    result = _build_calendar_section(db_session, space_id=space.id)
    assert result == ""


def test_calendar_section_not_excluded_for_other_space(db_session: Session):
    """Exclude from space A -> calling with space B still returns events."""
    ds = _make_calendar_datasource(db_session)
    space_a = _make_space(db_session, name="Space A")
    space_b = _make_space(db_session, name="Space B")
    now = datetime.now(UTC)

    _make_event(db_session, ds.id, "Sprint Planning", now + timedelta(hours=4))
    _exclude_datasource_from_space(db_session, space_a.id, ds.id)

    result = _build_calendar_section(db_session, space_id=space_b.id)
    assert result != ""
    assert "Sprint Planning" in result


def test_calendar_section_no_space_id_always_returns(db_session: Session):
    """Odin (space_id=None) always returns events regardless of any exclusions."""
    ds = _make_calendar_datasource(db_session)
    space = _make_space(db_session, name="Some Space")
    now = datetime.now(UTC)

    _make_event(db_session, ds.id, "Board Meeting", now + timedelta(hours=2))
    _exclude_datasource_from_space(db_session, space.id, ds.id)

    # Even though there's an exclusion for *some* space, Odin (None) should see events.
    result = _build_calendar_section(db_session, space_id=None)
    assert result != ""
    assert "Board Meeting" in result


def test_calendar_section_formats_today_tomorrow(db_session: Session):
    """Events for today and tomorrow -> output contains 'Today' and 'Tomorrow' labels."""
    ds = _make_calendar_datasource(db_session)
    now = datetime.now(UTC).replace(tzinfo=None)
    today = now.date()
    tomorrow = today + timedelta(days=1)

    # Create an event later today (ensure it's in the future so the query picks it up).
    # Use 23:00 today to maximize the chance it's still "today" regardless of when tests run.
    today_event_start = datetime(today.year, today.month, today.day, 23, 0, 0)
    # If that's already in the past, the event won't show — but we're within 48h window
    # so create an event that's definitely in the future and definitely today.
    if today_event_start <= now:
        # Extremely late in the day — skip today label test gracefully.
        # This only happens if tests run between 23:00 and midnight.
        today_event_start = now + timedelta(minutes=5)

    tomorrow_event_start = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 10, 0, 0)

    _make_event(
        db_session, ds.id, "Today Event",
        today_event_start,
        today_event_start + timedelta(hours=1),
    )
    _make_event(
        db_session, ds.id, "Tomorrow Event",
        tomorrow_event_start,
        tomorrow_event_start + timedelta(hours=1),
    )

    result = _build_calendar_section(db_session)
    assert "Today" in result
    assert "Tomorrow" in result
    assert "Today Event" in result
    assert "Tomorrow Event" in result


def test_calendar_section_empty_events(db_session: Session):
    """DataSource exists but no events in next 48h -> returns empty string."""
    ds = _make_calendar_datasource(db_session)

    # Create an event far in the future (outside the 48h window)
    future = datetime.now(UTC) + timedelta(days=10)
    _make_event(db_session, ds.id, "Far Away Event", future)

    result = _build_calendar_section(db_session)
    assert result == ""


def test_calendar_section_truncates_to_budget(db_session: Session):
    """Many events -> output doesn't exceed ~2000 chars (plus wrapper overhead)."""
    ds = _make_calendar_datasource(db_session)
    now = datetime.now(UTC)

    # Create enough events to exceed 2000 chars.
    # Each event title is ~80 chars, plus formatting overhead (~30 chars per line).
    # 2000 / 110 ≈ 18, so 30 events should push well past the limit.
    for i in range(30):
        title = f"Very Long Meeting Title Number {i:03d} With Extra Description Text Padding"
        _make_event(
            db_session, ds.id, title,
            now + timedelta(hours=1, minutes=i * 10),
            attendees=[
                {"displayName": f"Person {j}", "email": f"p{j}@example.com"}
                for j in range(5)
            ],
            conference_data={"entryPoints": [{"entryPointType": "video"}]},
        )

    result = _build_calendar_section(db_session)
    assert result != ""

    # The inner content (inside user-data tags) is truncated to 2000 chars,
    # then wrapped. Total output should be under 2100 chars (2000 + wrapper).
    # Extract inner content between the user-data tags.
    assert len(result) < 2200, f"Calendar section too long: {len(result)} chars"
