"""Tests for records-related extensions to item_service (Phase 4.1)."""

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import item_service, space_service, todo_service


def _make_space(db: Session, name: str = "Test Space", template: str = "project"):
    return space_service.create_space(db, name=name, template=template)


def _make_crm_space(db: Session, name: str = "CRM Space"):
    space = space_service.create_space(db, name=name, template="crm")
    space_service.update_space(
        db,
        space.id,
        custom_field_schema=[
            {"name": "company", "type": "text"},
            {"name": "deal_value", "type": "number"},
            {"name": "email", "type": "text"},
        ],
    )
    return space_service.get_space(db, space.id)


# ---- validate_custom_fields ----


def test_validate_custom_fields_no_schema(db_session: Session):
    """No schema on space => validation is a no-op (no error)."""
    space = _make_space(db_session)
    # Should not raise
    item_service.validate_custom_fields(db_session, space.id, {"anything": "goes"})


def test_validate_custom_fields_valid(db_session: Session):
    space = _make_crm_space(db_session)
    # Known fields — should not raise
    item_service.validate_custom_fields(
        db_session, space.id, {"company": "Acme", "deal_value": 10000}
    )


def test_validate_custom_fields_unknown_logs_warning(db_session: Session, caplog):
    space = _make_crm_space(db_session)
    with caplog.at_level("WARNING"):
        item_service.validate_custom_fields(
            db_session, space.id, {"company": "Acme", "unknown_field": "x"}
        )
    assert "Unknown custom field 'unknown_field'" in caplog.text


def test_create_item_validates_custom_fields(db_session: Session, caplog):
    space = _make_crm_space(db_session)
    with caplog.at_level("WARNING"):
        item = item_service.create_item(
            db_session,
            space_id=space.id,
            title="Lead",
            item_type="record",
            custom_fields={"company": "Acme", "bogus": "val"},
        )
    assert item.custom_fields["company"] == "Acme"
    assert "Unknown custom field 'bogus'" in caplog.text


def test_update_item_validates_custom_fields(db_session: Session, caplog):
    space = _make_crm_space(db_session)
    item = item_service.create_item(
        db_session,
        space_id=space.id,
        title="Lead",
        item_type="record",
    )
    with caplog.at_level("WARNING"):
        item_service.update_item(
            db_session,
            item.id,
            custom_fields={"email": "a@b.com", "nonexistent": 42},
        )
    assert "Unknown custom field 'nonexistent'" in caplog.text


# ---- list_items with parent_record_id ----


def test_list_items_filter_by_parent_record_id(db_session: Session):
    space = _make_crm_space(db_session)
    parent = item_service.create_item(
        db_session, space_id=space.id, title="Parent Record", item_type="record"
    )
    child = item_service.create_item(
        db_session,
        space_id=space.id,
        title="Child Task",
        parent_record_id=parent.id,
    )
    other = item_service.create_item(
        db_session, space_id=space.id, title="Unrelated"
    )

    children = item_service.list_items(db_session, parent_record_id=parent.id)
    assert len(children) == 1
    assert children[0].id == child.id


# ---- list_items with sort_by / sort_order ----


def test_list_items_sort_by_title(db_session: Session):
    space = _make_space(db_session)
    item_service.create_item(db_session, space_id=space.id, title="Banana")
    item_service.create_item(db_session, space_id=space.id, title="Apple")
    item_service.create_item(db_session, space_id=space.id, title="Cherry")

    items = item_service.list_items(db_session, sort_by="title", sort_order="asc")
    titles = [i.title for i in items]
    assert titles == ["Apple", "Banana", "Cherry"]


def test_list_items_sort_by_title_desc(db_session: Session):
    space = _make_space(db_session)
    item_service.create_item(db_session, space_id=space.id, title="Banana")
    item_service.create_item(db_session, space_id=space.id, title="Apple")
    item_service.create_item(db_session, space_id=space.id, title="Cherry")

    items = item_service.list_items(db_session, sort_by="title", sort_order="desc")
    titles = [i.title for i in items]
    assert titles == ["Cherry", "Banana", "Apple"]


def test_list_items_sort_by_created_at(db_session: Session):
    space = _make_space(db_session)
    i1 = item_service.create_item(db_session, space_id=space.id, title="First")
    i2 = item_service.create_item(db_session, space_id=space.id, title="Second")

    items = item_service.list_items(db_session, sort_by="created_at", sort_order="asc")
    assert items[0].id == i1.id


def test_list_items_sort_default_is_sort_position(db_session: Session):
    space = _make_space(db_session)
    item_service.create_item(db_session, space_id=space.id, title="A")
    item_service.create_item(db_session, space_id=space.id, title="B")

    items = item_service.list_items(db_session)
    assert items[0].sort_position <= items[1].sort_position


# ---- get_record_with_children ----


def test_get_record_with_children(db_session: Session):
    space = _make_crm_space(db_session)
    record = item_service.create_item(
        db_session, space_id=space.id, title="Company Record", item_type="record"
    )
    child1 = item_service.create_item(
        db_session,
        space_id=space.id,
        title="Sub-task 1",
        parent_record_id=record.id,
    )
    child2 = item_service.create_item(
        db_session,
        space_id=space.id,
        title="Sub-task 2",
        parent_record_id=record.id,
    )

    result = item_service.get_record_with_children(db_session, record.id)
    assert result["record"].id == record.id
    assert len(result["child_records"]) == 2
    child_ids = {c.id for c in result["child_records"]}
    assert child1.id in child_ids
    assert child2.id in child_ids


def test_get_record_with_children_excludes_archived(db_session: Session):
    space = _make_crm_space(db_session)
    record = item_service.create_item(
        db_session, space_id=space.id, title="Record", item_type="record"
    )
    child = item_service.create_item(
        db_session,
        space_id=space.id,
        title="Active Child",
        parent_record_id=record.id,
    )
    archived_child = item_service.create_item(
        db_session,
        space_id=space.id,
        title="Archived Child",
        parent_record_id=record.id,
    )
    item_service.archive_item(db_session, archived_child.id)

    result = item_service.get_record_with_children(db_session, record.id)
    assert len(result["child_records"]) == 1
    assert result["child_records"][0].id == child.id


def test_get_record_with_children_includes_linked_todos(db_session: Session):
    space = _make_crm_space(db_session)
    record = item_service.create_item(
        db_session, space_id=space.id, title="Record", item_type="record"
    )
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Follow up")
    item_service.link_todo_to_record(db_session, todo.id, record.id)

    result = item_service.get_record_with_children(db_session, record.id)
    assert len(result["linked_todos"]) == 1
    assert result["linked_todos"][0].id == todo.id


def test_get_record_with_children_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        item_service.get_record_with_children(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


# ---- link_todo_to_record ----


def test_link_todo_to_record(db_session: Session):
    space = _make_crm_space(db_session)
    record = item_service.create_item(
        db_session, space_id=space.id, title="Record", item_type="record"
    )
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Call client")

    linked = item_service.link_todo_to_record(db_session, todo.id, record.id)
    assert linked.record_id == record.id


def test_link_todo_to_record_not_found_record(db_session: Session):
    space = _make_space(db_session)
    todo = todo_service.create_todo(db_session, space_id=space.id, title="Orphan")
    with pytest.raises(HTTPException) as exc_info:
        item_service.link_todo_to_record(db_session, todo.id, "nonexistent")
    assert exc_info.value.status_code == 404


def test_link_todo_to_record_not_found_todo(db_session: Session):
    space = _make_crm_space(db_session)
    record = item_service.create_item(
        db_session, space_id=space.id, title="Record", item_type="record"
    )
    with pytest.raises(HTTPException) as exc_info:
        item_service.link_todo_to_record(db_session, "nonexistent", record.id)
    assert exc_info.value.status_code == 404


# ---- Space custom_field_schema update ----


def test_space_custom_field_schema_update(db_session: Session):
    space = space_service.create_space(db_session, name="Schema Space", template="crm")
    assert space.custom_field_schema is None

    schema = [{"name": "revenue", "type": "number"}]
    updated = space_service.update_space(db_session, space.id, custom_field_schema=schema)
    assert updated.custom_field_schema == schema
