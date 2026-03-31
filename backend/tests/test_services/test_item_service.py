import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import ItemEvent
from backend.openloop.services import item_service, space_service


def _make_space(db: Session, name: str = "Test Space", template: str = "project"):
    return space_service.create_space(db, name=name, template=template)


def test_create_item(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="New Task")
    assert item.title == "New Task"
    assert item.item_type == "task"
    assert item.space_id == space.id
    assert item.archived is False
    assert item.created_by == "user"
    assert item.id is not None
    # Default stage should be first board column
    assert item.stage == space.board_columns[0]


def test_create_item_with_description(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(
        db_session, space_id=space.id, title="Described", description="Some details"
    )
    assert item.description == "Some details"


def test_create_item_with_priority(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Urgent", priority=1)
    assert item.priority == 1


def test_create_item_record_type(db_session: Session):
    space = _make_space(db_session, template="crm")
    item = item_service.create_item(
        db_session, space_id=space.id, title="A Lead", item_type="record"
    )
    assert item.item_type == "record"


def test_create_item_invalid_type(db_session: Session):
    space = _make_space(db_session)
    with pytest.raises(HTTPException) as exc_info:
        item_service.create_item(db_session, space_id=space.id, title="Bad", item_type="invalid")
    assert exc_info.value.status_code == 422


def test_create_item_space_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        item_service.create_item(db_session, space_id="nonexistent", title="Orphan")
    assert exc_info.value.status_code == 404


def test_create_item_invalid_stage(db_session: Session):
    space = _make_space(db_session)
    with pytest.raises(HTTPException) as exc_info:
        item_service.create_item(
            db_session, space_id=space.id, title="Bad Stage", stage="nonexistent"
        )
    assert exc_info.value.status_code == 422


def test_create_item_logs_created_event(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Tracked")
    events = db_session.query(ItemEvent).filter(ItemEvent.item_id == item.id).all()
    assert len(events) == 1
    assert events[0].event_type == "created"
    assert events[0].triggered_by == "user"


def test_create_item_sort_position_increments(db_session: Session):
    space = _make_space(db_session)
    i1 = item_service.create_item(db_session, space_id=space.id, title="First")
    i2 = item_service.create_item(db_session, space_id=space.id, title="Second")
    assert i2.sort_position > i1.sort_position


def test_get_item(db_session: Session):
    space = _make_space(db_session)
    created = item_service.create_item(db_session, space_id=space.id, title="Fetch Me")
    fetched = item_service.get_item(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.title == "Fetch Me"


def test_get_item_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        item_service.get_item(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_list_items_empty(db_session: Session):
    items = item_service.list_items(db_session)
    assert items == []


def test_list_items(db_session: Session):
    space = _make_space(db_session)
    item_service.create_item(db_session, space_id=space.id, title="A")
    item_service.create_item(db_session, space_id=space.id, title="B")
    items = item_service.list_items(db_session)
    assert len(items) == 2


def test_list_items_filter_by_space(db_session: Session):
    s1 = _make_space(db_session, name="S1")
    s2 = _make_space(db_session, name="S2")
    item_service.create_item(db_session, space_id=s1.id, title="In S1")
    item_service.create_item(db_session, space_id=s2.id, title="In S2")
    items = item_service.list_items(db_session, space_id=s1.id)
    assert len(items) == 1
    assert items[0].title == "In S1"


def test_list_items_filter_by_stage(db_session: Session):
    space = _make_space(db_session)
    item_service.create_item(db_session, space_id=space.id, title="Idea", stage="idea")
    item_service.create_item(db_session, space_id=space.id, title="Done", stage="done")
    items = item_service.list_items(db_session, stage="idea")
    assert len(items) == 1
    assert items[0].title == "Idea"


def test_list_items_filter_by_type(db_session: Session):
    space = _make_space(db_session)
    item_service.create_item(db_session, space_id=space.id, title="Task", item_type="task")
    item_service.create_item(db_session, space_id=space.id, title="Record", item_type="record")
    items = item_service.list_items(db_session, item_type="task")
    assert len(items) == 1
    assert items[0].title == "Task"


def test_list_items_excludes_archived(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Archived")
    item_service.archive_item(db_session, item.id)
    item_service.create_item(db_session, space_id=space.id, title="Active")
    items = item_service.list_items(db_session)
    assert len(items) == 1
    assert items[0].title == "Active"


def test_list_items_include_archived(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Archived")
    item_service.archive_item(db_session, item.id)
    items = item_service.list_items(db_session, archived=True)
    assert len(items) == 1
    assert items[0].title == "Archived"


def test_update_item_title(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Old")
    updated = item_service.update_item(db_session, item.id, title="New")
    assert updated.title == "New"


def test_update_item_description(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Item")
    updated = item_service.update_item(db_session, item.id, description="Added desc")
    assert updated.description == "Added desc"


def test_update_item_logs_event(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Track Update")
    item_service.update_item(db_session, item.id, title="Updated Title")
    events = db_session.query(ItemEvent).filter(ItemEvent.item_id == item.id).all()
    # 1 for create + 1 for update
    assert len(events) == 2
    update_event = [e for e in events if e.event_type == "updated"][0]
    assert update_event.old_value == "Track Update"
    assert update_event.new_value == "Updated Title"


def test_update_item_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        item_service.update_item(db_session, "nonexistent-id", title="Nope")
    assert exc_info.value.status_code == 404


def test_move_item(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Movable")
    moved = item_service.move_item(db_session, item.id, "in_progress")
    assert moved.stage == "in_progress"


def test_move_item_invalid_stage(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Bad Move")
    with pytest.raises(HTTPException) as exc_info:
        item_service.move_item(db_session, item.id, "nonexistent")
    assert exc_info.value.status_code == 422


def test_move_item_logs_event(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Move Track")
    old_stage = item.stage
    item_service.move_item(db_session, item.id, "done")
    events = db_session.query(ItemEvent).filter(ItemEvent.item_id == item.id).all()
    stage_events = [e for e in events if e.event_type == "stage_changed"]
    assert len(stage_events) == 1
    assert stage_events[0].old_value == old_stage
    assert stage_events[0].new_value == "done"


def test_move_item_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        item_service.move_item(db_session, "nonexistent-id", "done")
    assert exc_info.value.status_code == 404


def test_archive_item(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Archive Me")
    archived = item_service.archive_item(db_session, item.id)
    assert archived.archived is True


def test_archive_item_already_archived(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Already")
    item_service.archive_item(db_session, item.id)
    with pytest.raises(HTTPException) as exc_info:
        item_service.archive_item(db_session, item.id)
    assert exc_info.value.status_code == 409


def test_archive_item_logs_event(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Archive Track")
    item_service.archive_item(db_session, item.id)
    events = db_session.query(ItemEvent).filter(ItemEvent.item_id == item.id).all()
    archive_events = [e for e in events if e.event_type == "archived"]
    assert len(archive_events) == 1


def test_archive_item_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        item_service.archive_item(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404
