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


# ---- is_done parameter and toggle_done ----


def test_create_item_with_is_done(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(
        db_session, space_id=space.id, title="Already Done", is_done=True
    )
    assert item.is_done is True


def test_create_item_default_is_done_false(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Fresh")
    assert item.is_done is False


def test_toggle_done(db_session: Session):
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Toggle Me")
    assert item.is_done is False

    toggled = item_service.toggle_done(db_session, item.id)
    assert toggled.is_done is True

    toggled_back = item_service.toggle_done(db_session, item.id)
    assert toggled_back.is_done is False


def test_toggle_done_stage_sync_task(db_session: Session):
    """Toggling a task to done should move it to the done stage."""
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Task Sync")
    original_stage = item.stage
    assert original_stage != "done"

    toggled = item_service.toggle_done(db_session, item.id)
    assert toggled.is_done is True
    assert toggled.stage == "done"

    # Toggle back should return to first column
    toggled_back = item_service.toggle_done(db_session, item.id)
    assert toggled_back.is_done is False
    assert toggled_back.stage == space.board_columns[0]


def test_is_done_stage_sync_via_update(db_session: Session):
    """Setting is_done=True via update_item should move task to done stage."""
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Update Sync")
    updated = item_service.update_item(db_session, item.id, is_done=True)
    assert updated.is_done is True
    assert updated.stage == "done"


def test_move_to_done_sets_is_done_true(db_session: Session):
    """Moving a task to the done column should set is_done=True."""
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Move Sync")
    assert item.is_done is False

    moved = item_service.move_item(db_session, item.id, "done")
    assert moved.stage == "done"
    assert moved.is_done is True


def test_move_from_done_sets_is_done_false(db_session: Session):
    """Moving a task away from done column should set is_done=False."""
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Undone")
    item_service.move_item(db_session, item.id, "done")

    moved_back = item_service.move_item(db_session, item.id, "in_progress")
    assert moved_back.stage == "in_progress"
    assert moved_back.is_done is False


def test_record_no_stage_sync_on_is_done(db_session: Session):
    """Records should NOT trigger stage sync when is_done changes."""
    space = _make_space(db_session, template="crm")
    record = item_service.create_item(
        db_session, space_id=space.id, title="Record", item_type="record"
    )
    last_col = space.board_columns[-1]  # "closed" for CRM template

    # Move record to last column — records should NOT get is_done sync
    moved = item_service.move_item(db_session, record.id, last_col)
    assert moved.stage == last_col
    assert moved.is_done is False  # Records don't sync is_done


def test_list_items_filter_by_is_done(db_session: Session):
    space = _make_space(db_session)
    item_service.create_item(db_session, space_id=space.id, title="Open Task")
    done_item = item_service.create_item(db_session, space_id=space.id, title="Done Task")
    item_service.update_item(db_session, done_item.id, is_done=True)

    open_items = item_service.list_items(db_session, is_done=False)
    assert len(open_items) == 1
    assert open_items[0].title == "Open Task"

    done_items = item_service.list_items(db_session, is_done=True)
    assert len(done_items) == 1
    assert done_items[0].title == "Done Task"


def test_lightweight_creation_defaults(db_session: Session):
    """Creating with just title + space_id should default everything else."""
    space = _make_space(db_session)
    item = item_service.create_item(db_session, space_id=space.id, title="Quick Task")
    assert item.item_type == "task"
    assert item.is_done is False
    assert item.archived is False
    assert item.description is None
    assert item.priority is None
    assert item.stage == space.board_columns[0]
    assert item.created_by == "user"
