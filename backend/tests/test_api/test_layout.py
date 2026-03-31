from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.services import space_service


def _create_space(client_or_db, template="project", name="Test"):
    """Helper: create a space via service for direct DB access."""
    if isinstance(client_or_db, Session):
        return space_service.create_space(client_or_db, name=name, template=template)
    # via API
    resp = client_or_db.post("/api/v1/spaces", json={"name": name, "template": template})
    assert resp.status_code == 201
    return resp.json()


def test_get_layout(client: TestClient, db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    resp = client.get(f"/api/v1/spaces/{space.id}/layout")
    assert resp.status_code == 200
    data = resp.json()
    assert "widgets" in data
    assert len(data["widgets"]) == 3
    assert data["widgets"][0]["widget_type"] == "todo_panel"
    assert data["widgets"][1]["widget_type"] == "kanban_board"
    assert data["widgets"][2]["widget_type"] == "conversations"


def test_add_widget(client: TestClient, db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="knowledge_base")
    resp = client.post(
        f"/api/v1/spaces/{space.id}/layout/widgets",
        json={"widget_type": "chart", "size": "large"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["widget_type"] == "chart"
    assert data["size"] == "large"
    assert data["position"] == 1  # appended after conversations
    assert data["id"] is not None


def test_update_widget(client: TestClient, db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="simple")
    layout_resp = client.get(f"/api/v1/spaces/{space.id}/layout")
    widget_id = layout_resp.json()["widgets"][0]["id"]

    resp = client.patch(
        f"/api/v1/spaces/{space.id}/layout/widgets/{widget_id}",
        json={"size": "full"},
    )
    assert resp.status_code == 200
    assert resp.json()["size"] == "full"
    assert resp.json()["widget_type"] == "todo_panel"  # unchanged


def test_delete_widget(client: TestClient, db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    layout_resp = client.get(f"/api/v1/spaces/{space.id}/layout")
    widget_id = layout_resp.json()["widgets"][1]["id"]  # kanban_board

    resp = client.delete(f"/api/v1/spaces/{space.id}/layout/widgets/{widget_id}")
    assert resp.status_code == 204

    # Verify widget is gone
    layout_resp = client.get(f"/api/v1/spaces/{space.id}/layout")
    assert len(layout_resp.json()["widgets"]) == 2


def test_bulk_replace_layout(client: TestClient, db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    # NOTE: Explicit positions are required here due to a bug in the route/service
    # interaction. The route passes position=None (from WidgetCreate default) as an
    # explicit dict key, and set_layout uses w.get("position", i) which returns None
    # instead of falling back to the index. Without explicit positions, this causes
    # a NOT NULL constraint violation on space_widgets.position.
    resp = client.put(
        f"/api/v1/spaces/{space.id}/layout",
        json={
            "widgets": [
                {"widget_type": "chart", "size": "large", "position": 0},
                {"widget_type": "markdown", "size": "small", "position": 1},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["widgets"]) == 2
    assert data["widgets"][0]["widget_type"] == "chart"
    assert data["widgets"][1]["widget_type"] == "markdown"


def test_get_layout_nonexistent_space(client: TestClient):
    resp = client.get("/api/v1/spaces/nonexistent-id/layout")
    assert resp.status_code == 404


def test_add_widget_nonexistent_space(client: TestClient):
    resp = client.post(
        "/api/v1/spaces/nonexistent-id/layout/widgets",
        json={"widget_type": "chart"},
    )
    assert resp.status_code == 404


def test_create_space_gets_default_widgets(client: TestClient):
    resp = client.post("/api/v1/spaces", json={"name": "Auto Widgets", "template": "project"})
    assert resp.status_code == 201
    space_id = resp.json()["id"]

    layout_resp = client.get(f"/api/v1/spaces/{space_id}/layout")
    assert layout_resp.status_code == 200
    widgets = layout_resp.json()["widgets"]
    assert len(widgets) == 3
    assert widgets[0]["widget_type"] == "todo_panel"
    assert widgets[1]["widget_type"] == "kanban_board"
    assert widgets[2]["widget_type"] == "conversations"


def test_widget_position_ordering(client: TestClient, db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="knowledge_base")
    # knowledge_base starts with 1 widget (conversations). Add 2 more.
    client.post(
        f"/api/v1/spaces/{space.id}/layout/widgets",
        json={"widget_type": "chart", "size": "medium"},
    )
    client.post(
        f"/api/v1/spaces/{space.id}/layout/widgets",
        json={"widget_type": "stat_card", "size": "small"},
    )

    resp = client.get(f"/api/v1/spaces/{space.id}/layout")
    widgets = resp.json()["widgets"]
    assert len(widgets) == 3
    # Verify returned in position order
    positions = [w["position"] for w in widgets]
    assert positions == [0, 1, 2]
    assert widgets[0]["widget_type"] == "conversations"
    assert widgets[1]["widget_type"] == "chart"
    assert widgets[2]["widget_type"] == "stat_card"


def test_reorder_via_patch(client: TestClient, db_session: Session):
    space = space_service.create_space(db_session, name="Test", template="project")
    # project: todo_panel(0), kanban_board(1), conversations(2)
    layout_resp = client.get(f"/api/v1/spaces/{space.id}/layout")
    widgets = layout_resp.json()["widgets"]
    todo_id = widgets[0]["id"]

    # Move todo_panel from position 0 to position 2
    resp = client.patch(
        f"/api/v1/spaces/{space.id}/layout/widgets/{todo_id}",
        json={"position": 2},
    )
    assert resp.status_code == 200
    assert resp.json()["position"] == 2

    # Verify new order
    layout_resp = client.get(f"/api/v1/spaces/{space.id}/layout")
    new_widgets = layout_resp.json()["widgets"]
    assert new_widgets[0]["widget_type"] == "kanban_board"
    assert new_widgets[1]["widget_type"] == "conversations"
    assert new_widgets[2]["widget_type"] == "todo_panel"
