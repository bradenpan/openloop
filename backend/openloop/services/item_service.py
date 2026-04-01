import logging

from contract.enums import ItemType
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Item, ItemEvent, ItemLink, Space

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
    parent_item_id: str | None = None,
    is_agent_task: bool = False,
    is_done: bool = False,
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

    # Default to first column if board has columns and no stage specified
    if stage is None and space.board_columns:
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
        parent_item_id=parent_item_id,
        is_done=is_done,
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
    parent_item_id: str | None = None,
    is_done: bool | None = None,
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
    if parent_item_id is not None:
        query = query.filter(Item.parent_item_id == parent_item_id)
    if is_done is not None:
        query = query.filter(Item.is_done == is_done)

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
        "parent_item_id",
        "is_agent_task",
        "is_done",
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
                # Bidirectional stage sync for tasks when is_done changes
                if field == "is_done" and item.item_type == "task":
                    space = db.query(Space).filter(Space.id == item.space_id).first()
                    if space and space.board_columns:
                        if value:  # is_done = True
                            done_col = "done" if "done" in space.board_columns else space.board_columns[-1]
                            item.stage = done_col
                        else:  # is_done = False
                            item.stage = space.board_columns[0]
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

    # Sync is_done for tasks when moving to/from done column
    if item.item_type == "task":
        done_col = "done" if "done" in (space.board_columns or []) else (space.board_columns or [""])[-1]
        if stage == done_col:
            item.is_done = True
        else:
            item.is_done = False

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


def toggle_done(db: Session, item_id: str, triggered_by: str = "user") -> Item:
    """Toggle is_done on a task item with bidirectional stage sync."""
    item = get_item(db, item_id)
    new_done = not item.is_done
    old_done = item.is_done
    item.is_done = new_done

    # Stage sync for tasks only
    if item.item_type == "task":
        space = db.query(Space).filter(Space.id == item.space_id).first()
        if space and space.board_columns:
            if new_done:
                done_col = "done" if "done" in space.board_columns else space.board_columns[-1]
                item.stage = done_col
            else:
                item.stage = space.board_columns[0]

    _log_event(db, item.id, "toggled_done", old_value=str(old_done), new_value=str(new_done), triggered_by=triggered_by)
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
    """Return a record item with its child items and linked items."""
    item = get_item(db, record_id)

    children = (
        db.query(Item)
        .filter(Item.parent_item_id == record_id, Item.archived == False)  # noqa: E712
        .order_by(Item.sort_position.asc())
        .all()
    )

    linked_items = (
        db.query(Item)
        .join(
            ItemLink,
            ((ItemLink.source_item_id == record_id) & (ItemLink.target_item_id == Item.id))
            | ((ItemLink.target_item_id == record_id) & (ItemLink.source_item_id == Item.id)),
        )
        .filter(Item.archived == False)  # noqa: E712
        .all()
    )

    return {
        "record": item,
        "child_records": children,
        "linked_items": linked_items,
    }


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
