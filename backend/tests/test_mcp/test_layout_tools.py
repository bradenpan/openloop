import asyncio
import json

from sqlalchemy.orm import Session

from backend.openloop.agents.mcp_tools import (
    add_widget,
    get_space_layout,
    remove_widget,
    set_space_layout,
    update_widget,
)
from backend.openloop.services import layout_service, space_service


def test_get_space_layout(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    result = asyncio.run(get_space_layout(space.id, _db=db_session))
    parsed = json.loads(result)
    assert "result" in parsed
    assert len(parsed["result"]) == 3
    assert parsed["result"][0]["widget_type"] == "todo_panel"
    assert parsed["result"][1]["widget_type"] == "kanban_board"
    assert parsed["result"][2]["widget_type"] == "conversations"


def test_add_widget_tool(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="knowledge_base")
    result = asyncio.run(
        add_widget(space.id, "chart", size="large", _db=db_session)
    )
    parsed = json.loads(result)
    assert "result" in parsed
    assert parsed["result"]["widget_type"] == "chart"
    assert parsed["result"]["size"] == "large"
    assert parsed["result"]["position"] == 1  # appended after conversations


def test_update_widget_tool(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="simple")
    widgets = layout_service.get_layout(db_session, space.id)
    widget_id = widgets[0].id

    result = asyncio.run(
        update_widget(widget_id, size="full", config='{"show_done": true}', _db=db_session)
    )
    parsed = json.loads(result)
    assert "result" in parsed
    assert parsed["result"]["size"] == "full"
    assert parsed["result"]["config"] == {"show_done": True}


def test_remove_widget_tool(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    widgets = layout_service.get_layout(db_session, space.id)
    widget_id = widgets[1].id  # kanban_board

    result = asyncio.run(remove_widget(widget_id, _db=db_session))
    parsed = json.loads(result)
    assert "result" in parsed
    assert parsed["result"]["removed"] == widget_id

    # Verify removal
    layout = layout_service.get_layout(db_session, space.id)
    assert len(layout) == 2


def test_set_space_layout_tool(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    widgets_json = json.dumps([
        {"widget_type": "markdown", "size": "large"},
        {"widget_type": "stat_card", "size": "small"},
    ])

    result = asyncio.run(set_space_layout(space.id, widgets_json, _db=db_session))
    parsed = json.loads(result)
    assert "result" in parsed
    assert len(parsed["result"]) == 2
    assert parsed["result"][0]["widget_type"] == "markdown"
    assert parsed["result"][1]["widget_type"] == "stat_card"

    # Verify old widgets are gone
    layout = layout_service.get_layout(db_session, space.id)
    assert len(layout) == 2


def test_add_widget_with_config(db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="knowledge_base")
    config_str = json.dumps({"columns": ["name", "email"], "page_size": 25})

    result = asyncio.run(
        add_widget(space.id, "data_table", config=config_str, _db=db_session)
    )
    parsed = json.loads(result)
    assert "result" in parsed
    assert parsed["result"]["config"] == {"columns": ["name", "email"], "page_size": 25}
    assert parsed["result"]["widget_type"] == "data_table"
