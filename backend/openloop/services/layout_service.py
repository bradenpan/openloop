from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Space, SpaceWidget

# Default widgets — every space gets the same core set.
# Templates control default_view and board_columns (via space_service), not widget availability.
_CORE_WIDGETS: list[tuple[str, str]] = [
    ("todo_panel", "small"),
    ("kanban_board", "large"),
    ("data_table", "large"),
    ("conversations", "small"),
]

_TEMPLATE_WIDGETS: dict[str, list[tuple[str, str]]] = {
    "project": _CORE_WIDGETS,
    "crm": _CORE_WIDGETS,
    "knowledge_base": _CORE_WIDGETS,
    "simple": _CORE_WIDGETS,
}


def get_layout(db: Session, space_id: str) -> list[SpaceWidget]:
    """Get all widgets for a space, ordered by position."""
    # Verify space exists
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    return (
        db.query(SpaceWidget)
        .filter(SpaceWidget.space_id == space_id)
        .order_by(SpaceWidget.position)
        .all()
    )


def add_widget(
    db: Session,
    space_id: str,
    *,
    widget_type: str,
    position: int | None = None,
    size: str = "medium",
    config: dict | None = None,
) -> SpaceWidget:
    """Add a widget to a space at the given position. Shifts existing widgets."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    if position is None:
        # Append at end
        max_pos = (
            db.query(SpaceWidget)
            .filter(SpaceWidget.space_id == space_id)
            .count()
        )
        position = max_pos

    # Shift existing widgets at position >= N up by 1
    widgets_to_shift = (
        db.query(SpaceWidget)
        .filter(SpaceWidget.space_id == space_id, SpaceWidget.position >= position)
        .order_by(SpaceWidget.position.desc())
        .all()
    )
    for w in widgets_to_shift:
        w.position += 1

    widget = SpaceWidget(
        space_id=space_id,
        widget_type=widget_type,
        position=position,
        size=size,
        config=config,
    )
    db.add(widget)
    db.commit()
    db.refresh(widget)
    return widget


def update_widget(db: Session, space_id: str, widget_id: str, **kwargs) -> SpaceWidget:
    """Update a widget's properties. Supports size, config, and position."""
    widget = db.query(SpaceWidget).filter(SpaceWidget.id == widget_id).first()
    if not widget or widget.space_id != space_id:
        raise HTTPException(status_code=404, detail="Widget not found")

    new_position = kwargs.pop("position", None)

    for field, value in kwargs.items():
        if field in ("size", "config"):
            setattr(widget, field, value)

    if new_position is not None and new_position != widget.position:
        old_position = widget.position
        space_id = widget.space_id

        if new_position > old_position:
            # Moving down: shift widgets in (old, new] up by -1
            to_shift = (
                db.query(SpaceWidget)
                .filter(
                    SpaceWidget.space_id == space_id,
                    SpaceWidget.position > old_position,
                    SpaceWidget.position <= new_position,
                    SpaceWidget.id != widget_id,
                )
                .all()
            )
            for w in to_shift:
                w.position -= 1
        else:
            # Moving up: shift widgets in [new, old) down by +1
            to_shift = (
                db.query(SpaceWidget)
                .filter(
                    SpaceWidget.space_id == space_id,
                    SpaceWidget.position >= new_position,
                    SpaceWidget.position < old_position,
                    SpaceWidget.id != widget_id,
                )
                .all()
            )
            for w in to_shift:
                w.position += 1

        widget.position = new_position

    db.commit()
    db.refresh(widget)
    return widget


def remove_widget(db: Session, space_id: str, widget_id: str) -> None:
    """Remove a widget and close the position gap."""
    widget = db.query(SpaceWidget).filter(SpaceWidget.id == widget_id).first()
    if not widget or widget.space_id != space_id:
        raise HTTPException(status_code=404, detail="Widget not found")

    space_id = widget.space_id
    removed_position = widget.position

    db.delete(widget)

    # Close the gap: shift widgets above the removed position down by 1
    widgets_to_shift = (
        db.query(SpaceWidget)
        .filter(SpaceWidget.space_id == space_id, SpaceWidget.position > removed_position)
        .order_by(SpaceWidget.position)
        .all()
    )
    for w in widgets_to_shift:
        w.position -= 1

    db.commit()


def set_layout(db: Session, space_id: str, widgets: list[dict]) -> list[SpaceWidget]:
    """Bulk replace all widgets for a space."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Delete all existing widgets
    db.query(SpaceWidget).filter(SpaceWidget.space_id == space_id).delete()

    # Insert fresh — always assign sequential positions regardless of input
    new_widgets = []
    for i, w in enumerate(widgets):
        widget = SpaceWidget(
            space_id=space_id,
            widget_type=w["widget_type"],
            position=i,
            size=w.get("size", "medium"),
            config=w.get("config"),
        )
        db.add(widget)
        new_widgets.append(widget)

    db.commit()
    for w in new_widgets:
        db.refresh(w)

    return sorted(new_widgets, key=lambda w: w.position)


def create_default_widgets(db: Session, space_id: str, template: str) -> list[SpaceWidget]:
    """Create default widgets for a space based on its template."""
    widget_defs = _TEMPLATE_WIDGETS.get(template, _TEMPLATE_WIDGETS["simple"])

    new_widgets = []
    for i, (widget_type, size) in enumerate(widget_defs):
        widget = SpaceWidget(
            space_id=space_id,
            widget_type=widget_type,
            position=i,
            size=size,
        )
        db.add(widget)
        new_widgets.append(widget)

    db.commit()
    for w in new_widgets:
        db.refresh(w)

    return new_widgets
