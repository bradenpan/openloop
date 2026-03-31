import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import space_service, todo_service


def _make_space(db: Session, name: str = "Test Space", template: str = "project"):
    return space_service.create_space(db, name=name, template=template)


def test_create_todo(db_session: Session):
    space = _make_space(db_session)
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Buy milk")
    assert todo.title == "Buy milk"
    assert todo.space_id == space.id
    assert todo.is_done is False
    assert todo.created_by == "user"
    assert todo.sort_position == 0.0
    assert todo.id is not None


def test_create_todo_with_due_date(db_session: Session):
    from datetime import UTC, datetime

    space = _make_space(db_session)
    due = datetime(2026, 4, 15, tzinfo=UTC)
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Deadline", due_date=due)
    assert todo.due_date is not None


def test_create_todo_space_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        todo_service.create_todo(db_session, space_id="nonexistent", title="Orphan")
    assert exc_info.value.status_code == 404


def test_create_todo_sort_position_increments(db_session: Session):
    space = _make_space(db_session)
    t1 = todo_service.create_todo(db_session, space_id=space.id, title="First")
    t2 = todo_service.create_todo(db_session, space_id=space.id, title="Second")
    assert t2.sort_position > t1.sort_position


def test_get_todo(db_session: Session):
    space = _make_space(db_session)
    created = todo_service.create_todo(db_session, space_id=space.id, title="Fetch Me")
    fetched = todo_service.get_todo(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.title == "Fetch Me"


def test_get_todo_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        todo_service.get_todo(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_list_todos_empty(db_session: Session):
    todos = todo_service.list_todos(db_session)
    assert todos == []


def test_list_todos(db_session: Session):
    space = _make_space(db_session)
    todo_service.create_todo(db_session, space_id=space.id, title="A")
    todo_service.create_todo(db_session, space_id=space.id, title="B")
    todos = todo_service.list_todos(db_session)
    assert len(todos) == 2


def test_list_todos_filter_by_space(db_session: Session):
    s1 = _make_space(db_session, name="Space1")
    s2 = _make_space(db_session, name="Space2")
    todo_service.create_todo(db_session, space_id=s1.id, title="In S1")
    todo_service.create_todo(db_session, space_id=s2.id, title="In S2")
    todos = todo_service.list_todos(db_session, space_id=s1.id)
    assert len(todos) == 1
    assert todos[0].title == "In S1"


def test_list_todos_filter_by_is_done(db_session: Session):
    space = _make_space(db_session)
    todo_service.create_todo(db_session, space_id=space.id, title="Open")
    t = todo_service.create_todo(db_session, space_id=space.id, title="Done")
    todo_service.update_todo(db_session, t.id, is_done=True)
    open_todos = todo_service.list_todos(db_session, is_done=False)
    assert len(open_todos) == 1
    assert open_todos[0].title == "Open"


def test_list_todos_excludes_promoted(db_session: Session):
    space = _make_space(db_session)
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Will promote")
    todo_service.promote_to_item(db_session, todo.id)
    todos = todo_service.list_todos(db_session)
    assert len(todos) == 0


def test_update_todo_title(db_session: Session):
    space = _make_space(db_session)
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Old")
    updated = todo_service.update_todo(db_session, todo.id, title="New")
    assert updated.title == "New"


def test_update_todo_is_done(db_session: Session):
    space = _make_space(db_session)
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Task")
    updated = todo_service.update_todo(db_session, todo.id, is_done=True)
    assert updated.is_done is True


def test_update_todo_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        todo_service.update_todo(db_session, "nonexistent-id", title="Nope")
    assert exc_info.value.status_code == 404


def test_update_todo_no_changes(db_session: Session):
    space = _make_space(db_session)
    todo = todo_service.create_todo(db_session, space_id=space.id, title="NoOp")
    updated = todo_service.update_todo(db_session, todo.id)
    assert updated.title == "NoOp"


def test_delete_todo(db_session: Session):
    space = _make_space(db_session)
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Delete Me")
    todo_service.delete_todo(db_session, todo.id)
    with pytest.raises(HTTPException) as exc_info:
        todo_service.get_todo(db_session, todo.id)
    assert exc_info.value.status_code == 404


def test_delete_todo_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        todo_service.delete_todo(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_promote_to_item(db_session: Session):
    space = _make_space(db_session, template="project")
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Promote Me")
    item = todo_service.promote_to_item(db_session, todo.id)
    assert item.title == "Promote Me"
    assert item.item_type == "task"
    assert item.space_id == space.id
    # Default stage should be first board column
    assert item.stage == space.board_columns[0]
    # Todo should be linked
    refreshed_todo = todo_service.get_todo(db_session, todo.id)
    assert refreshed_todo.promoted_to_item_id == item.id


def test_promote_to_item_with_stage(db_session: Session):
    space = _make_space(db_session, template="project")
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Staged")
    item = todo_service.promote_to_item(db_session, todo.id, stage="in_progress")
    assert item.stage == "in_progress"


def test_promote_to_item_already_promoted(db_session: Session):
    space = _make_space(db_session, template="project")
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Already Done")
    todo_service.promote_to_item(db_session, todo.id)
    with pytest.raises(HTTPException) as exc_info:
        todo_service.promote_to_item(db_session, todo.id)
    assert exc_info.value.status_code == 409


def test_promote_to_item_no_board(db_session: Session):
    space = _make_space(db_session, name="Simple Space", template="simple")
    todo = todo_service.create_todo(db_session, space_id=space.id, title="No Board")
    with pytest.raises(HTTPException) as exc_info:
        todo_service.promote_to_item(db_session, todo.id)
    assert exc_info.value.status_code == 422


def test_promote_to_item_invalid_stage(db_session: Session):
    space = _make_space(db_session, template="project")
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Bad Stage")
    with pytest.raises(HTTPException) as exc_info:
        todo_service.promote_to_item(db_session, todo.id, stage="nonexistent_stage")
    assert exc_info.value.status_code == 422
