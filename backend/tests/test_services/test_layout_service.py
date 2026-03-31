import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import layout_service, space_service


def test_get_layout_empty(db_session: Session):
    """New space with no widgets returns empty list when we bypass default creation."""
    space = space_service.create_space(db_session, name="Test", template="project")
    # Remove default widgets so we can test empty
    from backend.openloop.db.models import SpaceWidget

    db_session.query(SpaceWidget).filter(SpaceWidget.space_id == space.id).delete()
    db_session.commit()

    result = layout_service.get_layout(db_session, space.id)
    assert result == []


def test_create_default_widgets_project(db_session: Session):
    space = space_service.create_space(db_session, name="Project", template="project")
    widgets = layout_service.get_layout(db_session, space.id)
    assert len(widgets) == 3
    assert widgets[0].widget_type == "todo_panel"
    assert widgets[0].size == "small"
    assert widgets[1].widget_type == "kanban_board"
    assert widgets[1].size == "large"
    assert widgets[2].widget_type == "conversations"
    assert widgets[2].size == "small"
    # Positions should be sequential
    assert [w.position for w in widgets] == [0, 1, 2]


def test_create_default_widgets_crm(db_session: Session):
    space = space_service.create_space(db_session, name="CRM", template="crm")
    widgets = layout_service.get_layout(db_session, space.id)
    assert len(widgets) == 3
    assert widgets[0].widget_type == "todo_panel"
    assert widgets[1].widget_type == "data_table"
    assert widgets[1].size == "large"
    assert widgets[2].widget_type == "conversations"


def test_create_default_widgets_knowledge_base(db_session: Session):
    space = space_service.create_space(db_session, name="KB", template="knowledge_base")
    widgets = layout_service.get_layout(db_session, space.id)
    assert len(widgets) == 1
    assert widgets[0].widget_type == "conversations"
    assert widgets[0].size == "large"


def test_create_default_widgets_simple(db_session: Session):
    space = space_service.create_space(db_session, name="Simple", template="simple")
    widgets = layout_service.get_layout(db_session, space.id)
    assert len(widgets) == 2
    assert widgets[0].widget_type == "todo_panel"
    assert widgets[1].widget_type == "conversations"


def test_add_widget_appends(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="knowledge_base")
    # knowledge_base starts with 1 widget (conversations at position 0)
    widget = layout_service.add_widget(db_session, space.id, widget_type="chart", size="medium")
    assert widget.position == 1
    assert widget.widget_type == "chart"
    layout = layout_service.get_layout(db_session, space.id)
    assert len(layout) == 2
    assert layout[1].id == widget.id


def test_add_widget_at_position_shifts(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    # project starts with: todo_panel(0), kanban_board(1), conversations(2)
    original_layout = layout_service.get_layout(db_session, space.id)
    kanban_id = original_layout[1].id
    conv_id = original_layout[2].id

    widget = layout_service.add_widget(
        db_session, space.id, widget_type="chart", position=1, size="small"
    )
    assert widget.position == 1

    layout = layout_service.get_layout(db_session, space.id)
    assert len(layout) == 4
    assert layout[1].widget_type == "chart"
    # The old kanban_board should now be at position 2
    assert layout[2].id == kanban_id
    assert layout[2].position == 2
    # conversations should be at position 3
    assert layout[3].id == conv_id
    assert layout[3].position == 3


def test_update_widget_size(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="simple")
    widgets = layout_service.get_layout(db_session, space.id)
    widget_id = widgets[0].id

    updated = layout_service.update_widget(db_session, widget_id, size="full")
    assert updated.size == "full"
    assert updated.position == 0  # unchanged


def test_update_widget_config(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="simple")
    widgets = layout_service.get_layout(db_session, space.id)
    widget_id = widgets[0].id

    updated = layout_service.update_widget(
        db_session, widget_id, config={"show_completed": True}
    )
    assert updated.config == {"show_completed": True}
    assert updated.size == "large"  # unchanged from default


def test_update_widget_position_move_down(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    # project: todo_panel(0), kanban_board(1), conversations(2)
    widgets = layout_service.get_layout(db_session, space.id)
    todo_id = widgets[0].id
    kanban_id = widgets[1].id
    conv_id = widgets[2].id

    # Move todo_panel from position 0 to position 2
    updated = layout_service.update_widget(db_session, todo_id, position=2)
    assert updated.position == 2

    layout = layout_service.get_layout(db_session, space.id)
    assert layout[0].id == kanban_id
    assert layout[0].position == 0
    assert layout[1].id == conv_id
    assert layout[1].position == 1
    assert layout[2].id == todo_id
    assert layout[2].position == 2


def test_update_widget_position_move_up(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    # project: todo_panel(0), kanban_board(1), conversations(2)
    widgets = layout_service.get_layout(db_session, space.id)
    todo_id = widgets[0].id
    kanban_id = widgets[1].id
    conv_id = widgets[2].id

    # Move conversations from position 2 to position 0
    updated = layout_service.update_widget(db_session, conv_id, position=0)
    assert updated.position == 0

    layout = layout_service.get_layout(db_session, space.id)
    assert layout[0].id == conv_id
    assert layout[0].position == 0
    assert layout[1].id == todo_id
    assert layout[1].position == 1
    assert layout[2].id == kanban_id
    assert layout[2].position == 2


def test_remove_widget_closes_gap(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    # project: todo_panel(0), kanban_board(1), conversations(2)
    widgets = layout_service.get_layout(db_session, space.id)
    todo_id = widgets[0].id
    kanban_id = widgets[1].id
    conv_id = widgets[2].id

    # Remove kanban_board (middle widget)
    layout_service.remove_widget(db_session, kanban_id)

    layout = layout_service.get_layout(db_session, space.id)
    assert len(layout) == 2
    assert layout[0].id == todo_id
    assert layout[0].position == 0
    assert layout[1].id == conv_id
    assert layout[1].position == 1


def test_set_layout_bulk_replace(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    # project starts with 3 widgets; replace with 2 new ones
    new_widgets = layout_service.set_layout(
        db_session,
        space.id,
        [
            {"widget_type": "chart", "size": "large"},
            {"widget_type": "markdown", "size": "small"},
        ],
    )
    assert len(new_widgets) == 2
    assert new_widgets[0].widget_type == "chart"
    assert new_widgets[0].position == 0
    assert new_widgets[1].widget_type == "markdown"
    assert new_widgets[1].position == 1

    # Verify old widgets are gone
    layout = layout_service.get_layout(db_session, space.id)
    assert len(layout) == 2
    types = [w.widget_type for w in layout]
    assert "todo_panel" not in types
    assert "kanban_board" not in types


def test_get_layout_invalid_space(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        layout_service.get_layout(db_session, "nonexistent-id")
    assert exc_info.value.status_code == 404


def test_add_widget_invalid_space(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        layout_service.add_widget(db_session, "nonexistent-id", widget_type="chart")
    assert exc_info.value.status_code == 404
