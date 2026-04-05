import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import data_source_service, space_service


def _make_space(db: Session, name: str = "DS Space"):
    return space_service.create_space(db, name=name, template="project")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_data_source(db_session: Session):
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=space.id, name="My Source", source_type="google_drive"
    )
    assert ds.name == "My Source"
    assert ds.source_type == "google_drive"
    assert ds.space_id == space.id
    assert ds.status == "active"
    assert ds.id is not None


def test_create_data_source_with_config(db_session: Session):
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session,
        space_id=space.id,
        name="Configured",
        source_type="api",
        config={"url": "https://example.com"},
        refresh_schedule="daily",
    )
    assert ds.config == {"url": "https://example.com"}
    assert ds.refresh_schedule == "daily"


def test_create_data_source_invalid_space(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        data_source_service.create_data_source(
            db_session, space_id="nonexistent", name="Bad", source_type="local"
        )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_data_source(db_session: Session):
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=space.id, name="GetMe", source_type="local"
    )
    fetched = data_source_service.get_data_source(db_session, ds.id)
    assert fetched.id == ds.id
    assert fetched.name == "GetMe"


def test_get_data_source_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        data_source_service.get_data_source(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_data_sources_empty(db_session: Session):
    result = data_source_service.list_data_sources(db_session)
    assert result == []


def test_list_data_sources_with_data(db_session: Session):
    space = _make_space(db_session)
    data_source_service.create_data_source(
        db_session, space_id=space.id, name="A", source_type="local"
    )
    data_source_service.create_data_source(
        db_session, space_id=space.id, name="B", source_type="api"
    )
    result = data_source_service.list_data_sources(db_session)
    assert len(result) == 2


def test_list_data_sources_filter_by_space(db_session: Session):
    s1 = _make_space(db_session, name="Space1")
    s2 = _make_space(db_session, name="Space2")
    data_source_service.create_data_source(
        db_session, space_id=s1.id, name="DS1", source_type="local"
    )
    data_source_service.create_data_source(
        db_session, space_id=s2.id, name="DS2", source_type="local"
    )
    result = data_source_service.list_data_sources(db_session, space_id=s1.id)
    assert len(result) == 1
    assert result[0].name == "DS1"


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_data_source(db_session: Session):
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=space.id, name="Old", source_type="local"
    )
    updated = data_source_service.update_data_source(db_session, ds.id, name="New")
    assert updated.name == "New"


def test_update_data_source_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        data_source_service.update_data_source(db_session, "nonexistent", name="X")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_data_source(db_session: Session):
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=space.id, name="Del", source_type="local"
    )
    data_source_service.delete_data_source(db_session, ds.id)
    with pytest.raises(HTTPException) as exc_info:
        data_source_service.get_data_source(db_session, ds.id)
    assert exc_info.value.status_code == 404


def test_delete_data_source_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        data_source_service.delete_data_source(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# System-level data sources
# ---------------------------------------------------------------------------


def test_create_data_source_system_level(db_session: Session):
    """space_id=None creates a system-level data source."""
    ds = data_source_service.create_data_source(
        db_session, space_id=None, name="System DS", source_type="google_calendar"
    )
    assert ds.space_id is None
    assert ds.name == "System DS"


def test_list_system_data_sources(db_session: Session):
    """list_system_data_sources returns only system (space_id IS NULL) sources."""
    space = _make_space(db_session)
    data_source_service.create_data_source(
        db_session, space_id=None, name="System", source_type="google_calendar"
    )
    data_source_service.create_data_source(
        db_session, space_id=space.id, name="Space-bound", source_type="local"
    )
    result = data_source_service.list_system_data_sources(db_session)
    assert len(result) == 1
    assert result[0].name == "System"


def test_list_data_sources_system_true(db_session: Session):
    """list_data_sources(system=True) returns only system sources."""
    space = _make_space(db_session)
    data_source_service.create_data_source(
        db_session, space_id=None, name="Sys", source_type="api"
    )
    data_source_service.create_data_source(
        db_session, space_id=space.id, name="Space", source_type="local"
    )
    result = data_source_service.list_data_sources(db_session, system=True)
    assert len(result) == 1
    assert result[0].name == "Sys"


def test_list_data_sources_system_false(db_session: Session):
    """list_data_sources(system=False) returns only space-bound sources."""
    space = _make_space(db_session)
    data_source_service.create_data_source(
        db_session, space_id=None, name="Sys", source_type="api"
    )
    data_source_service.create_data_source(
        db_session, space_id=space.id, name="Space", source_type="local"
    )
    result = data_source_service.list_data_sources(db_session, system=False)
    assert len(result) == 1
    assert result[0].name == "Space"


# ---------------------------------------------------------------------------
# Exclusions
# ---------------------------------------------------------------------------


def test_exclude_from_space(db_session: Session):
    """exclude_from_space creates an exclusion row."""
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=None, name="Cal", source_type="google_calendar"
    )
    data_source_service.exclude_from_space(db_session, space.id, ds.id)
    assert data_source_service.is_excluded(db_session, space.id, ds.id) is True


def test_exclude_from_space_idempotent(db_session: Session):
    """Calling exclude_from_space twice does not error."""
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=None, name="Cal", source_type="google_calendar"
    )
    data_source_service.exclude_from_space(db_session, space.id, ds.id)
    data_source_service.exclude_from_space(db_session, space.id, ds.id)  # no error
    assert data_source_service.is_excluded(db_session, space.id, ds.id) is True


def test_exclude_rejects_space_level_source(db_session: Session):
    """Only system data sources can be excluded — space-level raises 422."""
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=space.id, name="Local", source_type="local"
    )
    with pytest.raises(HTTPException) as exc_info:
        data_source_service.exclude_from_space(db_session, space.id, ds.id)
    assert exc_info.value.status_code == 422


def test_include_in_space_removes_exclusion(db_session: Session):
    """include_in_space removes an existing exclusion."""
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=None, name="Cal", source_type="google_calendar"
    )
    data_source_service.exclude_from_space(db_session, space.id, ds.id)
    assert data_source_service.is_excluded(db_session, space.id, ds.id) is True

    data_source_service.include_in_space(db_session, space.id, ds.id)
    assert data_source_service.is_excluded(db_session, space.id, ds.id) is False


def test_include_in_space_validates_space_exists(db_session: Session):
    """include_in_space raises 404 for nonexistent space."""
    ds = data_source_service.create_data_source(
        db_session, space_id=None, name="Cal", source_type="google_calendar"
    )
    with pytest.raises(HTTPException) as exc_info:
        data_source_service.include_in_space(db_session, "nonexistent-space", ds.id)
    assert exc_info.value.status_code == 404


def test_include_in_space_validates_ds_exists(db_session: Session):
    """include_in_space raises 404 for nonexistent data source."""
    space = _make_space(db_session)
    with pytest.raises(HTTPException) as exc_info:
        data_source_service.include_in_space(db_session, space.id, "nonexistent-ds")
    assert exc_info.value.status_code == 404


def test_is_excluded_returns_false_when_not_excluded(db_session: Session):
    """is_excluded returns False for non-excluded data source."""
    space = _make_space(db_session)
    ds = data_source_service.create_data_source(
        db_session, space_id=None, name="Cal", source_type="google_calendar"
    )
    assert data_source_service.is_excluded(db_session, space.id, ds.id) is False
