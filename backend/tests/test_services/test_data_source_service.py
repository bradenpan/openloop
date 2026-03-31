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
