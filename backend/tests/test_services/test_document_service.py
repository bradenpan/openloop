import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import document_service, space_service


def _make_space(db: Session, name: str = "Doc Space"):
    return space_service.create_space(db, name=name, template="project")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_document(db_session: Session):
    space = _make_space(db_session)
    doc = document_service.create_document(db_session, space_id=space.id, title="Design Doc")
    assert doc.title == "Design Doc"
    assert doc.source == "local"
    assert doc.space_id == space.id
    assert doc.id is not None


def test_create_document_with_all_fields(db_session: Session):
    space = _make_space(db_session)
    doc = document_service.create_document(
        db_session,
        space_id=space.id,
        title="Drive Doc",
        source="google_drive",
        drive_file_id="abc123",
        drive_folder_id="folder456",
        tags=["design", "v2"],
    )
    assert doc.source == "google_drive"
    assert doc.drive_file_id == "abc123"
    assert doc.tags == ["design", "v2"]


def test_create_document_invalid_space(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        document_service.create_document(db_session, space_id="nonexistent", title="Bad")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_document(db_session: Session):
    space = _make_space(db_session)
    doc = document_service.create_document(db_session, space_id=space.id, title="GetMe")
    fetched = document_service.get_document(db_session, doc.id)
    assert fetched.id == doc.id
    assert fetched.title == "GetMe"


def test_get_document_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        document_service.get_document(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_documents_empty(db_session: Session):
    result = document_service.list_documents(db_session)
    assert result == []


def test_list_documents_with_data(db_session: Session):
    space = _make_space(db_session)
    document_service.create_document(db_session, space_id=space.id, title="A")
    document_service.create_document(db_session, space_id=space.id, title="B")
    result = document_service.list_documents(db_session)
    assert len(result) == 2


def test_list_documents_filter_by_space(db_session: Session):
    s1 = _make_space(db_session, name="Space1")
    s2 = _make_space(db_session, name="Space2")
    document_service.create_document(db_session, space_id=s1.id, title="D1")
    document_service.create_document(db_session, space_id=s2.id, title="D2")
    result = document_service.list_documents(db_session, space_id=s1.id)
    assert len(result) == 1
    assert result[0].title == "D1"


def test_list_documents_search(db_session: Session):
    space = _make_space(db_session)
    document_service.create_document(db_session, space_id=space.id, title="Architecture Guide")
    document_service.create_document(db_session, space_id=space.id, title="Setup Notes")
    result = document_service.list_documents(db_session, search="architecture")
    assert len(result) == 1
    assert result[0].title == "Architecture Guide"


def test_list_documents_search_escapes_wildcards(db_session: Session):
    space = _make_space(db_session)
    document_service.create_document(db_session, space_id=space.id, title="100% Done")
    document_service.create_document(db_session, space_id=space.id, title="Other")
    result = document_service.list_documents(db_session, search="100%")
    assert len(result) == 1
    assert result[0].title == "100% Done"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_document(db_session: Session):
    space = _make_space(db_session)
    doc = document_service.create_document(db_session, space_id=space.id, title="Del")
    document_service.delete_document(db_session, doc.id)
    with pytest.raises(HTTPException) as exc_info:
        document_service.get_document(db_session, doc.id)
    assert exc_info.value.status_code == 404


def test_delete_document_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        document_service.delete_document(db_session, "nonexistent")
    assert exc_info.value.status_code == 404
