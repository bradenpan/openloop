import logging

from contract.enums import ItemType
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Item, ItemEvent, Space, Todo

logger = logging.getLogger(__name__)


def create_item(
    db: Session,
    *,
    space_id: str,
    title: str,
    item_type: str = "task",
    description: str | None = None,
    stage: str | None = None,
    priority: int | None = None,
    custom_fields: dict | None = None,
    due_date=None,
    created_by: str = "user",
    source_conversation_id: str | None = None,
    assigned_agent_id: str | None = None,
    parent_record_id: str | None = None,
    is_agent_task: bool = False,
) -> Item:
    """Create a board item (task or record) in a space."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    if item_type not in [t.value for t in ItemType]:
        raise HTTPException(status_code=422, detail=f"Invalid item_type: {item_type}")

    # Validate stage if provided
    if stage and space.board_columns and stage not in space.board_columns:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid stage '{stage}'. Valid: {space.board_columns}",
        )

    # Validate custom fields against space schema
    if custom_fields:
        validate_custom_fields(db, space_id, custom_fields)

    # Default to first column if board is enabled and no stage specified
    if stage is None and space.board_enabled and space.board_columns:
        stage = space.board_columns[0]

    # Get next sort position within the stage
    max_pos = (
        db.query(Item.sort_position)
        .filter(Item.space_id == space_id, Item.stage == stage, Item.archived == False)  # noqa: E712
        .order_by(Item.sort_position.desc())
        .first()
    )
    next_pos = (max_pos[0] + 1.0) if max_pos else 0.0

    item = Item(
        space_id=space_id,
        item_type=item_type,
        is_agent_task=is_agent_task,
        title=title,
        description=description,
        stage=stage,
        priority=priority,
        sort_position=next_pos,
        custom_fields=custom_fields,
        parent_record_id=parent_record_id,
        assigned_agent_id=assigned_agent_id,
        due_date=due_date,
        created_by=created_by,
        source_conversation_id=source_conversation_id,
    )
    db.add(item)
    db.flush()

    # Log creation event
    _log_event(db, item.id, "created", triggered_by=created_by)

    db.commit()
    db.refresh(item)
    return item


def get_item(db: Session, item_id: str) -> Item:
    """Get a board item by ID, or 404."""
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def list_items(
    db: Session,
    *,
    space_id: str | None = None,
    stage: str | None = None,
    item_type: str | None = None,
    parent_record_id: str | None = None,
    archived: bool = False,
    sort_by: str | None = None,
    sort_order: str = "asc",
    limit: int = 50,
    offset: int = 0,
) -> list[Item]:
    """List board items with optional filters."""
    query = db.query(Item).filter(Item.archived == archived)
    if space_id is not None:
        query = query.filter(Item.space_id == space_id)
    if stage is not None:
        query = query.filter(Item.stage == stage)
    if item_type is not None:
        query = query.filter(Item.item_type == item_type)
    if parent_record_id is not None:
        query = query.filter(Item.parent_record_id == parent_record_id)

    # Determine sort column
    _sortable = {
        "title": Item.title,
        "created_at": Item.created_at,
        "updated_at": Item.updated_at,
        "due_date": Item.due_date,
        "stage": Item.stage,
        "sort_position": Item.sort_position,
    }
    sort_col = _sortable.get(sort_by, Item.sort_position)
    order = sort_col.desc() if sort_order == "desc" else sort_col.asc()

    return query.order_by(order).offset(offset).limit(limit).all()


def update_item(db: Session, item_id: str, triggered_by: str = "user", **kwargs) -> Item:
    """Update a board item. Uses exclude_unset pattern."""
    item = get_item(db, item_id)

    # Validate custom fields if provided
    if "custom_fields" in kwargs and kwargs["custom_fields"] is not None:
        validate_custom_fields(db, item.space_id, kwargs["custom_fields"])

    updatable = {
        "title",
        "description",
        "priority",
        "sort_position",
        "custom_fields",
        "due_date",
        "assigned_agent_id",
        "parent_record_id",
        "is_agent_task",
    }
    for field, value in kwargs.items():
        if field in updatable:
            old_value = getattr(item, field)
            setattr(item, field, value)
            if old_value != value:
                _log_event(
                    db,
                    item.id,
                    "updated",
                    old_value=str(old_value),
                    new_value=str(value),
                    triggered_by=triggered_by,
                )
    db.commit()
    db.refresh(item)
    return item


def move_item(db: Session, item_id: str, stage: str, triggered_by: str = "user") -> Item:
    """Move a board item to a new stage, with validation."""
    item = get_item(db, item_id)
    space = db.query(Space).filter(Space.id == item.space_id).first()

    if space and space.board_columns and stage not in space.board_columns:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid stage '{stage}'. Valid: {space.board_columns}",
        )

    old_stage = item.stage
    item.stage = stage
    _log_event(
        db,
        item.id,
        "stage_changed",
        old_value=old_stage,
        new_value=stage,
        triggered_by=triggered_by,
    )
    db.commit()
    db.refresh(item)
    return item


def archive_item(db: Session, item_id: str, triggered_by: str = "user") -> Item:
    """Archive a board item."""
    item = get_item(db, item_id)
    if item.archived:
        raise HTTPException(status_code=409, detail="Item already archived")
    item.archived = True
    _log_event(db, item.id, "archived", triggered_by=triggered_by)
    db.commit()
    db.refresh(item)
    return item


def validate_custom_fields(db: Session, space_id: str, custom_fields: dict) -> None:
    """Validate custom_fields against the space's custom_field_schema.

    Logs warnings for unknown fields but does not reject them (lenient).
    """
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space or not space.custom_field_schema:
        return

    schema_names = {f["name"] for f in space.custom_field_schema if "name" in f}
    for field_name in custom_fields:
        if field_name not in schema_names:
            logger.warning(
                "Unknown custom field '%s' for space %s (valid: %s)",
                field_name,
                space_id,
                schema_names,
            )


def get_record_with_children(db: Session, record_id: str) -> dict:
    """Return a record item with its child items and linked todos."""
    item = get_item(db, record_id)

    children = (
        db.query(Item)
        .filter(Item.parent_record_id == record_id, Item.archived == False)  # noqa: E712
        .order_by(Item.sort_position.asc())
        .all()
    )
    linked_todos = (
        db.query(Todo)
        .filter(Todo.record_id == record_id)
        .order_by(Todo.sort_position.asc())
        .all()
    )

    return {
        "record": item,
        "child_records": children,
        "linked_todos": linked_todos,
    }


def link_todo_to_record(db: Session, todo_id: str, record_id: str) -> Todo:
    """Link a todo to a record by setting record_id on the todo."""
    # Verify record exists
    record = db.query(Item).filter(Item.id == record_id).first()
    if not record:
        raise HTTPException(status_code=404, detail="Record not found")

    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")

    todo.record_id = record_id
    db.commit()
    db.refresh(todo)
    return todo


def _log_event(
    db: Session,
    item_id: str,
    event_type: str,
    *,
    old_value: str | None = None,
    new_value: str | None = None,
    triggered_by: str = "user",
) -> ItemEvent:
    """Log an item event for audit/stale detection."""
    event = ItemEvent(
        item_id=item_id,
        event_type=event_type,
        old_value=old_value,
        new_value=new_value,
        triggered_by=triggered_by,
    )
    db.add(event)
    return event
