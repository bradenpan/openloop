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


# ---- List items with parent_item_id filter ----


def test_list_items_filter_parent_item_id(client: TestClient):
    space = _create_crm_space(client)
    parent = _create_item(client, space["id"], title="Parent", item_type="record")
    child = _create_item(
        client, space["id"], title="Child", parent_item_id=parent["id"]
    )
    _create_item(client, space["id"], title="Unrelated")

    resp = client.get(f"/api/v1/items?parent_item_id={parent['id']}")
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
    _create_item(
        client, space["id"], title="Task 1", parent_item_id=record["id"]
    )
    _create_item(
        client, space["id"], title="Task 2", parent_item_id=record["id"]
    )

    resp = client.get(f"/api/v1/items/{record['id']}/children")
    assert resp.status_code == 200
    data = resp.json()
    assert data["record"]["id"] == record["id"]
    assert len(data["child_records"]) == 2
    assert len(data["linked_items"]) == 0


def test_get_record_children_with_linked_items(client: TestClient):
    space = _create_crm_space(client)
    record = _create_item(client, space["id"], title="Company", item_type="record")
    task = _create_item(client, space["id"], title="Follow up call")

    # Link task to record via link endpoint
    resp = client.post(
        f"/api/v1/items/{record['id']}/links",
        json={"target_item_id": task["id"]},
    )
    assert resp.status_code == 201

    # Check children endpoint
    resp = client.get(f"/api/v1/items/{record['id']}/children")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["linked_items"]) == 1
    assert data["linked_items"][0]["id"] == task["id"]


def test_get_record_children_not_found(client: TestClient):
    resp = client.get("/api/v1/items/nonexistent/children")
    assert resp.status_code == 404


# ---- POST /items/{item_id}/links ----


def test_link_item_to_record(client: TestClient):
    space = _create_crm_space(client)
    record = _create_item(client, space["id"], title="Record", item_type="record")
    task = _create_item(client, space["id"], title="Call client")

    resp = client.post(
        f"/api/v1/items/{record['id']}/links",
        json={"target_item_id": task["id"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_item_id"] == record["id"]
    assert data["target_item_id"] == task["id"]


def test_link_item_not_found_source(client: TestClient):
    space = _create_space(client)
    task = _create_item(client, space["id"], title="Task")

    resp = client.post(
        "/api/v1/items/nonexistent/links",
        json={"target_item_id": task["id"]},
    )
    assert resp.status_code == 404


def test_link_item_not_found_target(client: TestClient):
    space = _create_crm_space(client)
    record = _create_item(client, space["id"], title="Record", item_type="record")

    resp = client.post(
        f"/api/v1/items/{record['id']}/links",
        json={"target_item_id": "nonexistent"},
    )
    assert resp.status_code == 404
