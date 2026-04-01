import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import space_service


def test_create_space_project(db_session: Session):
    space = space_service.create_space(db_session, name="My Project", template="project")
    assert space.name == "My Project"
    assert space.template == "project"
    assert space.board_enabled is True
    assert space.default_view == "board"
    assert space.board_columns == ["idea", "scoping", "todo", "in_progress", "done"]
    assert space.id is not None


def test_create_space_crm(db_session: Session):
    space = space_service.create_space(db_session, name="Sales CRM", template="crm")
    assert space.board_enabled is True
    assert space.default_view == "table"
    assert "lead" in space.board_columns


def test_create_space_knowledge_base(db_session: Session):
    space = space_service.create_space(db_session, name="Wiki", template="knowledge_base")
    assert space.board_enabled is True
    assert space.default_view == "list"
    assert space.board_columns == ["todo", "in_progress", "done"]


def test_create_space_simple(db_session: Session):
    space = space_service.create_space(db_session, name="Personal", template="simple")
    assert space.board_enabled is True
    assert space.default_view == "list"
    assert space.board_columns == ["todo", "in_progress", "done"]


def test_create_space_with_description(db_session: Session):
    space = space_service.create_space(
        db_session, name="Docs", template="simple", description="My personal docs"
    )
    assert space.description == "My personal docs"


def test_create_space_duplicate_name(db_session: Session):
    space_service.create_space(db_session, name="Unique", template="simple")
    with pytest.raises(HTTPException) as exc_info:
        space_service.create_space(db_session, name="Unique", template="simple")
    assert exc_info.value.status_code == 409


def test_create_space_invalid_template(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        space_service.create_space(db_session, name="Bad", template="nonexistent")
    assert exc_info.value.status_code == 422


def test_get_space(db_session: Session):
    created = space_service.create_space(db_session, name="Fetch Me", template="project")
    fetched = space_service.get_space(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.name == "Fetch Me"


def test_get_space_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        space_service.get_space(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_list_spaces_empty(db_session: Session):
    spaces = space_service.list_spaces(db_session)
    assert spaces == []


def test_list_spaces(db_session: Session):
    space_service.create_space(db_session, name="A", template="simple")
    space_service.create_space(db_session, name="B", template="project")
    spaces = space_service.list_spaces(db_session)
    assert len(spaces) == 2


def test_update_space_name(db_session: Session):
    space = space_service.create_space(db_session, name="Old Name", template="simple")
    updated = space_service.update_space(db_session, space.id, name="New Name")
    assert updated.name == "New Name"


def test_update_space_duplicate_name(db_session: Session):
    space_service.create_space(db_session, name="Taken", template="simple")
    space = space_service.create_space(db_session, name="Other", template="simple")
    with pytest.raises(HTTPException) as exc_info:
        space_service.update_space(db_session, space.id, name="Taken")
    assert exc_info.value.status_code == 409


def test_update_space_board_columns(db_session: Session):
    space = space_service.create_space(db_session, name="Custom", template="project")
    updated = space_service.update_space(
        db_session, space.id, board_columns=["backlog", "doing", "done"]
    )
    assert updated.board_columns == ["backlog", "doing", "done"]


def test_update_space_partial(db_session: Session):
    space = space_service.create_space(
        db_session, name="Partial", template="project", description="original"
    )
    updated = space_service.update_space(db_session, space.id, description="changed")
    assert updated.description == "changed"
    assert updated.name == "Partial"  # unchanged


def test_update_space_clear_description_to_null(db_session: Session):
    """Verify that explicitly setting a field to None clears it."""
    space = space_service.create_space(
        db_session, name="Clearable", template="simple", description="has desc"
    )
    assert space.description == "has desc"
    updated = space_service.update_space(db_session, space.id, description=None)
    assert updated.description is None


def test_update_space_no_changes(db_session: Session):
    """Empty update (no kwargs) should be a no-op."""
    space = space_service.create_space(db_session, name="NoOp", template="simple")
    updated = space_service.update_space(db_session, space.id)
    assert updated.name == "NoOp"


def test_update_space_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        space_service.update_space(db_session, "nonexistent-id", name="Nope")
    assert exc_info.value.status_code == 404


def test_delete_space(db_session: Session):
    space = space_service.create_space(db_session, name="Delete Me", template="simple")
    space_service.delete_space(db_session, space.id)
    with pytest.raises(HTTPException) as exc_info:
        space_service.get_space(db_session, space.id)
    assert exc_info.value.status_code == 404


def test_delete_space_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        space_service.delete_space(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404
