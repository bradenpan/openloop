from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Item, Space, Todo


def create_todo(
    db: Session,
    *,
    space_id: str,
    title: str,
    due_date: datetime | None = None,
    created_by: str = "user",
    source_conversation_id: str | None = None,
) -> Todo:
    """Create a to-do in a space."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Get next sort position
    max_pos = (
        db.query(Todo.sort_position)
        .filter(Todo.space_id == space_id, Todo.is_done == False)  # noqa: E712
        .order_by(Todo.sort_position.desc())
        .first()
    )
    next_pos = (max_pos[0] + 1.0) if max_pos else 0.0

    todo = Todo(
        space_id=space_id,
        title=title,
        due_date=due_date,
        sort_position=next_pos,
        created_by=created_by,
        source_conversation_id=source_conversation_id,
    )
    db.add(todo)
    db.commit()
    db.refresh(todo)
    return todo


def get_todo(db: Session, todo_id: str) -> Todo:
    """Get a to-do by ID, or 404."""
    todo = db.query(Todo).filter(Todo.id == todo_id).first()
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return todo


def list_todos(
    db: Session,
    *,
    space_id: str | None = None,
    is_done: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Todo]:
    """List to-dos with optional filters. Cross-space if no space_id."""
    query = db.query(Todo).filter(Todo.promoted_to_item_id == None)  # noqa: E711
    if space_id is not None:
        query = query.filter(Todo.space_id == space_id)
    if is_done is not None:
        query = query.filter(Todo.is_done == is_done)
    return query.order_by(Todo.sort_position.asc()).offset(offset).limit(limit).all()


def update_todo(db: Session, todo_id: str, **kwargs) -> Todo:
    """Update a to-do. Uses exclude_unset pattern."""
    todo = get_todo(db, todo_id)
    updatable = {"title", "is_done", "due_date", "sort_position"}
    for field, value in kwargs.items():
        if field in updatable:
            setattr(todo, field, value)
    db.commit()
    db.refresh(todo)
    return todo


def delete_todo(db: Session, todo_id: str) -> None:
    """Delete a to-do by ID, or 404."""
    todo = get_todo(db, todo_id)
    db.delete(todo)
    db.commit()


def promote_to_item(
    db: Session,
    todo_id: str,
    *,
    stage: str | None = None,
) -> Item:
    """Promote a to-do to a board item. The to-do is hidden (not deleted)."""
    todo = get_todo(db, todo_id)

    if todo.promoted_to_item_id is not None:
        raise HTTPException(status_code=409, detail="Todo already promoted")

    space = db.query(Space).filter(Space.id == todo.space_id).first()
    if not space or not space.board_enabled:
        raise HTTPException(status_code=422, detail="Space does not have a board enabled")

    # Default to first column if no stage specified
    if stage is None and space.board_columns:
        stage = space.board_columns[0]

    # Validate stage against space columns
    if stage and space.board_columns and stage not in space.board_columns:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid stage '{stage}'. Valid: {space.board_columns}",
        )

    item = Item(
        space_id=todo.space_id,
        item_type="task",
        title=todo.title,
        description=None,
        stage=stage,
        due_date=todo.due_date,
        created_by=todo.created_by,
        source_conversation_id=todo.source_conversation_id,
    )
    db.add(item)
    db.flush()  # Get item.id before setting FK

    todo.promoted_to_item_id = item.id
    db.commit()
    db.refresh(item)
    return item
