"""API tests for records-related endpoints (Phase 4.1)."""

from fastapi.testclient import TestClient


def _create_space(client: TestClient, name: str = "Test Space", template: str = "project") -> dict:
    resp = client.post("/api/v1/spaces", json={"name": name, "template": template})
    assert resp.status_code == 201
    return resp.json()


def _create_crm_space(client: TestClient, name: str = "CRM Space") -> dict:
    space = _create_space(client, name=name, template="crm")
    schema = [
        {"name": "company", "type": "text"},
        {"name": "deal_value", "type": "number"},
    ]
    resp = client.patch(
        f"/api/v1/spaces/{space['id']}",
        json={"custom_field_schema": schema},
    )
    assert resp.status_code == 200
    return resp.json()


def _create_item(client: TestClient, space_id: str, **kwargs) -> dict:
    payload = {"space_id": space_id, "title": kwargs.pop("title", "Item"), **kwargs}
    resp = client.post("/api/v1/items", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _create_todo(client: TestClient, space_id: str, title: str = "Todo") -> dict:
    resp = client.post("/api/v1/todos", json={"space_id": space_id, "title": title})
    assert resp.status_code == 201
    return resp.json()


# ---- Space custom_field_schema ----


def test_space_response_includes_custom_field_schema(client: TestClient):
    space = _create_space(client, template="crm")
    assert space["custom_field_schema"] is None


def test_update_space_custom_field_schema(client: TestClient):
    space = _create_space(client, template="crm")
    schema = [{"name": "company", "type": "text"}]
    resp = client.patch(
        f"/api/v1/spaces/{space['id']}",
        json={"custom_field_schema": schema},
    )
    assert resp.status_code == 200
    assert resp.json()["custom_field_schema"] == schema


def test_get_field_schema_empty(client: TestClient):
    space = _create_space(client)
    resp = client.get(f"/api/v1/spaces/{space['id']}/field-schema")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_field_schema_with_data(client: TestClient):
    space = _create_crm_space(client)
    resp = client.get(f"/api/v1/spaces/{space['id']}/field-schema")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert data[0]["name"] == "company"


def test_get_field_schema_not_found(client: TestClient):
    resp = client.get("/api/v1/spaces/nonexistent/field-schema")
    assert resp.status_code == 404


# ---- List items with parent_record_id filter ----


def test_list_items_filter_parent_record_id(client: TestClient):
    space = _create_crm_space(client)
    parent = _create_item(client, space["id"], title="Parent", item_type="record")
    child = _create_item(
        client, space["id"], title="Child", parent_record_id=parent["id"]
    )
    _create_item(client, space["id"], title="Unrelated")

    resp = client.get(f"/api/v1/items?parent_record_id={parent['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == child["id"]


# ---- List items with sort_by / sort_order ----


def test_list_items_sort_by_title_asc(client: TestClient):
    space = _create_space(client)
    _create_item(client, space["id"], title="Banana")
    _create_item(client, space["id"], title="Apple")
    _create_item(client, space["id"], title="Cherry")

    resp = client.get("/api/v1/items?sort_by=title&sort_order=asc")
    assert resp.status_code == 200
    titles = [item["title"] for item in resp.json()]
    assert titles == ["Apple", "Banana", "Cherry"]


def test_list_items_sort_by_title_desc(client: TestClient):
    space = _create_space(client)
    _create_item(client, space["id"], title="Banana")
    _create_item(client, space["id"], title="Apple")
    _create_item(client, space["id"], title="Cherry")

    resp = client.get("/api/v1/items?sort_by=title&sort_order=desc")
    assert resp.status_code == 200
    titles = [item["title"] for item in resp.json()]
    assert titles == ["Cherry", "Banana", "Apple"]


def test_list_items_sort_by_created_at(client: TestClient):
    space = _create_space(client)
    i1 = _create_item(client, space["id"], title="First")
    i2 = _create_item(client, space["id"], title="Second")

    resp = client.get("/api/v1/items?sort_by=created_at&sort_order=desc")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["id"] == i2["id"]
    assert data[1]["id"] == i1["id"]


# ---- GET /items/{item_id}/children ----


def test_get_record_children(client: TestClient):
    space = _create_crm_space(client)
    record = _create_item(client, space["id"], title="Company", item_type="record")
    child1 = _create_item(
        client, space["id"], title="Task 1", parent_record_id=record["id"]
    )
    child2 = _create_item(
        client, space["id"], title="Task 2", parent_record_id=record["id"]
    )

    resp = client.get(f"/api/v1/items/{record['id']}/children")
    assert resp.status_code == 200
    data = resp.json()
    assert data["record"]["id"] == record["id"]
    assert len(data["child_records"]) == 2
    assert len(data["linked_todos"]) == 0


def test_get_record_children_with_linked_todos(client: TestClient):
    space = _create_crm_space(client)
    record = _create_item(client, space["id"], title="Company", item_type="record")
    todo = _create_todo(client, space["id"], title="Follow up call")

    # Link todo to record
    resp = client.post(
        f"/api/v1/items/{record['id']}/link-todo",
        json={"todo_id": todo["id"]},
    )
    assert resp.status_code == 200

    # Check children endpoint
    resp = client.get(f"/api/v1/items/{record['id']}/children")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["linked_todos"]) == 1
    assert data["linked_todos"][0]["id"] == todo["id"]


def test_get_record_children_not_found(client: TestClient):
    resp = client.get("/api/v1/items/nonexistent/children")
    assert resp.status_code == 404


# ---- POST /items/{record_id}/link-todo ----


def test_link_todo_to_record(client: TestClient):
    space = _create_crm_space(client)
    record = _create_item(client, space["id"], title="Record", item_type="record")
    todo = _create_todo(client, space["id"], title="Call client")

    resp = client.post(
        f"/api/v1/items/{record['id']}/link-todo",
        json={"todo_id": todo["id"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["record_id"] == record["id"]


def test_link_todo_to_record_not_found_record(client: TestClient):
    space = _create_space(client)
    todo = _create_todo(client, space["id"])

    resp = client.post(
        "/api/v1/items/nonexistent/link-todo",
        json={"todo_id": todo["id"]},
    )
    assert resp.status_code == 404


def test_link_todo_to_record_not_found_todo(client: TestClient):
    space = _create_crm_space(client)
    record = _create_item(client, space["id"], title="Record", item_type="record")

    resp = client.post(
        f"/api/v1/items/{record['id']}/link-todo",
        json={"todo_id": "nonexistent"},
    )
    assert resp.status_code == 404
