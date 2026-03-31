from contract.enums import SpaceTemplate
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Space
from backend.openloop.services import layout_service

# Default board columns per template
_TEMPLATE_DEFAULTS: dict[str, dict] = {
    "project": {
        "board_enabled": True,
        "default_view": "board",
        "board_columns": ["idea", "scoping", "todo", "in_progress", "done"],
    },
    "crm": {
        "board_enabled": True,
        "default_view": "table",
        "board_columns": ["lead", "contacted", "qualifying", "negotiation", "closed"],
    },
    "knowledge_base": {
        "board_enabled": False,
        "default_view": None,
        "board_columns": None,
    },
    "simple": {
        "board_enabled": False,
        "default_view": None,
        "board_columns": None,
    },
}

# Fields that can be updated via PATCH
_UPDATABLE_FIELDS = {"name", "description", "board_enabled", "default_view", "board_columns", "custom_field_schema"}


def create_space(db: Session, *, name: str, template: str, description: str | None = None) -> Space:
    """Create a new space with template defaults."""
    if template not in [t.value for t in SpaceTemplate]:
        raise HTTPException(status_code=422, detail=f"Invalid template: {template}")

    existing = db.query(Space).filter(Space.name == name).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Space with name '{name}' already exists")

    defaults = _TEMPLATE_DEFAULTS.get(template, _TEMPLATE_DEFAULTS["simple"])

    space = Space(
        name=name,
        template=template,
        description=description,
        board_enabled=defaults["board_enabled"],
        default_view=defaults["default_view"],
        board_columns=defaults["board_columns"],
    )
    db.add(space)
    db.commit()
    db.refresh(space)

    # Create default widgets for the new space
    layout_service.create_default_widgets(db, space.id, template)

    return space


def get_space(db: Session, space_id: str) -> Space:
    """Get a space by ID, or 404."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")
    return space


def list_spaces(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[Space]:
    """List all spaces, ordered by creation time (newest first)."""
    return db.query(Space).order_by(Space.created_at.desc()).offset(offset).limit(limit).all()


def update_space(db: Session, space_id: str, **kwargs) -> Space:
    """Update a space. Only explicitly provided fields are changed.

    Uses **kwargs from model_dump(exclude_unset=True) so that:
    - Absent fields are not touched
    - Fields explicitly set to None ARE set to None (e.g., clearing description)
    """
    space = get_space(db, space_id)

    for field, value in kwargs.items():
        if field not in _UPDATABLE_FIELDS:
            continue
        if field == "name" and value is not None:
            existing = db.query(Space).filter(Space.name == value, Space.id != space_id).first()
            if existing:
                raise HTTPException(
                    status_code=409, detail=f"Space with name '{value}' already exists"
                )
        setattr(space, field, value)

    db.commit()
    db.refresh(space)
    return space


def delete_space(db: Session, space_id: str) -> None:
    """Delete a space by ID, or 404."""
    space = get_space(db, space_id)
    db.delete(space)
    db.commit()
