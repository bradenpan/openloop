from fastapi.testclient import TestClient


def _create_space(client: TestClient, name: str = "Test Space", template: str = "project") -> dict:
    resp = client.post("/api/v1/spaces", json={"name": name, "template": template})
    assert resp.status_code == 201
    return resp.json()


def test_create_item(client: TestClient):
    space = _create_space(client)
    resp = client.post(
        "/api/v1/items",
        json={"space_id": space["id"], "title": "New Task"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "New Task"
    assert data["item_type"] == "task"
    assert data["space_id"] == space["id"]
    assert data["archived"] is False
    assert data["id"] is not None


def test_create_item_with_details(client: TestClient):
    space = _create_space(client)
    resp = client.post(
        "/api/v1/items",
        json={
            "space_id": space["id"],
            "title": "Detailed",
            "description": "Full details",
            "priority": 1,
            "stage": "todo",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "Full details"
    assert data["priority"] == 1
    assert data["stage"] == "todo"


def test_create_item_record_type(client: TestClient):
    space = _create_space(client, template="crm")
    resp = client.post(
        "/api/v1/items",
        json={"space_id": space["id"], "title": "A Lead", "item_type": "record"},
    )
    assert resp.status_code == 201
    assert resp.json()["item_type"] == "record"


def test_create_item_invalid_type(client: TestClient):
    space = _create_space(client)
    resp = client.post(
        "/api/v1/items",
        json={"space_id": space["id"], "title": "Bad", "item_type": "invalid"},
    )
    assert resp.status_code == 422


def test_create_item_space_not_found(client: TestClient):
    resp = client.post(
        "/api/v1/items",
        json={"space_id": "nonexistent", "title": "Orphan"},
    )
    assert resp.status_code == 404


def test_create_item_invalid_stage(client: TestClient):
    space = _create_space(client)
    resp = client.post(
        "/api/v1/items",
        json={"space_id": space["id"], "title": "Bad Stage", "stage": "nonexistent"},
    )
    assert resp.status_code == 422


def test_list_items_empty(client: TestClient):
    resp = client.get("/api/v1/items")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_items(client: TestClient):
    space = _create_space(client)
    client.post("/api/v1/items", json={"space_id": space["id"], "title": "A"})
    client.post("/api/v1/items", json={"space_id": space["id"], "title": "B"})
    resp = client.get("/api/v1/items")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_items_filter_by_space(client: TestClient):
    s1 = _create_space(client, name="S1")
    s2 = _create_space(client, name="S2")
    client.post("/api/v1/items", json={"space_id": s1["id"], "title": "In S1"})
    client.post("/api/v1/items", json={"space_id": s2["id"], "title": "In S2"})
    resp = client.get(f"/api/v1/items?space_id={s1['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "In S1"


def test_list_items_filter_by_stage(client: TestClient):
    space = _create_space(client)
    client.post("/api/v1/items", json={"space_id": space["id"], "title": "Idea", "stage": "idea"})
    client.post("/api/v1/items", json={"space_id": space["id"], "title": "Done", "stage": "done"})
    resp = client.get("/api/v1/items?stage=idea")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Idea"


def test_get_item(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Fetch Me"})
    item_id = create_resp.json()["id"]
    resp = client.get(f"/api/v1/items/{item_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Fetch Me"


def test_get_item_not_found(client: TestClient):
    resp = client.get("/api/v1/items/nonexistent")
    assert resp.status_code == 404


def test_update_item(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Old"})
    item_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/items/{item_id}", json={"title": "New"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "New"


def test_update_item_partial(client: TestClient):
    space = _create_space(client)
    create_resp = client.post(
        "/api/v1/items",
        json={"space_id": space["id"], "title": "Partial", "description": "original"},
    )
    item_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/items/{item_id}", json={"description": "changed"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["description"] == "changed"
    assert data["title"] == "Partial"


def test_update_item_empty_body(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/items", json={"space_id": space["id"], "title": "NoOp"})
    item_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/items/{item_id}", json={})
    assert resp.status_code == 200
    assert resp.json()["title"] == "NoOp"


def test_update_item_not_found(client: TestClient):
    resp = client.patch("/api/v1/items/nonexistent", json={"title": "Nope"})
    assert resp.status_code == 404


def test_move_item(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Movable"})
    item_id = create_resp.json()["id"]
    resp = client.post(f"/api/v1/items/{item_id}/move", json={"stage": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["stage"] == "in_progress"


def test_move_item_invalid_stage(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Bad Move"})
    item_id = create_resp.json()["id"]
    resp = client.post(f"/api/v1/items/{item_id}/move", json={"stage": "nonexistent"})
    assert resp.status_code == 422


def test_move_item_not_found(client: TestClient):
    resp = client.post("/api/v1/items/nonexistent/move", json={"stage": "done"})
    assert resp.status_code == 404


def test_archive_item(client: TestClient):
    space = _create_space(client)
    create_resp = client.post(
        "/api/v1/items", json={"space_id": space["id"], "title": "Archive Me"}
    )
    item_id = create_resp.json()["id"]
    resp = client.post(f"/api/v1/items/{item_id}/archive")
    assert resp.status_code == 200
    assert resp.json()["archived"] is True


def test_archive_item_already_archived(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Already"})
    item_id = create_resp.json()["id"]
    client.post(f"/api/v1/items/{item_id}/archive")
    resp = client.post(f"/api/v1/items/{item_id}/archive")
    assert resp.status_code == 409


def test_archive_item_not_found(client: TestClient):
    resp = client.post("/api/v1/items/nonexistent/archive")
    assert resp.status_code == 404


def test_get_item_events(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Events"})
    item_id = create_resp.json()["id"]
    resp = client.get(f"/api/v1/items/{item_id}/events")
    assert resp.status_code == 200
    events = resp.json()
    # Should have a "created" event at minimum
    assert len(events) >= 1
    assert events[0]["event_type"] == "created"


def test_get_item_events_after_move(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Track"})
    item_id = create_resp.json()["id"]
    client.post(f"/api/v1/items/{item_id}/move", json={"stage": "done"})
    resp = client.get(f"/api/v1/items/{item_id}/events")
    assert resp.status_code == 200
    events = resp.json()
    event_types = [e["event_type"] for e in events]
    assert "created" in event_types
    assert "stage_changed" in event_types


def test_get_item_events_after_archive(client: TestClient):
    space = _create_space(client)
    create_resp = client.post(
        "/api/v1/items", json={"space_id": space["id"], "title": "Archive Track"}
    )
    item_id = create_resp.json()["id"]
    client.post(f"/api/v1/items/{item_id}/archive")
    resp = client.get(f"/api/v1/items/{item_id}/events")
    assert resp.status_code == 200
    events = resp.json()
    event_types = [e["event_type"] for e in events]
    assert "archived" in event_types


def test_get_item_events_not_found(client: TestClient):
    resp = client.get("/api/v1/items/nonexistent/events")
    assert resp.status_code == 404


# ---- is_done filter ----


def test_list_items_filter_by_is_done(client: TestClient):
    space = _create_space(client)
    client.post("/api/v1/items", json={"space_id": space["id"], "title": "Open"})
    create_resp = client.post(
        "/api/v1/items",
        json={"space_id": space["id"], "title": "Done", "is_done": True},
    )
    assert create_resp.status_code == 201

    resp = client.get("/api/v1/items?is_done=false")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Open"

    resp = client.get("/api/v1/items?is_done=true")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Done"


def test_create_item_with_is_done(client: TestClient):
    space = _create_space(client)
    resp = client.post(
        "/api/v1/items",
        json={"space_id": space["id"], "title": "Pre-done", "is_done": True},
    )
    assert resp.status_code == 201
    assert resp.json()["is_done"] is True


# ---- Link endpoints ----


def test_create_item_link(client: TestClient):
    space = _create_space(client)
    item1 = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Item A"}).json()
    item2 = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Item B"}).json()

    resp = client.post(
        f"/api/v1/items/{item1['id']}/links",
        json={"target_item_id": item2["id"]},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_item_id"] == item1["id"]
    assert data["target_item_id"] == item2["id"]
    assert data["link_type"] == "related_to"


def test_list_item_links(client: TestClient):
    space = _create_space(client)
    item1 = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Item A"}).json()
    item2 = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Item B"}).json()

    client.post(
        f"/api/v1/items/{item1['id']}/links",
        json={"target_item_id": item2["id"]},
    )

    resp = client.get(f"/api/v1/items/{item1['id']}/links")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1

    # Bidirectional: item2 should also see the link
    resp = client.get(f"/api/v1/items/{item2['id']}/links")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_delete_item_link(client: TestClient):
    space = _create_space(client)
    item1 = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Item A"}).json()
    item2 = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Item B"}).json()

    link_resp = client.post(
        f"/api/v1/items/{item1['id']}/links",
        json={"target_item_id": item2["id"]},
    )
    link_id = link_resp.json()["id"]

    resp = client.delete(f"/api/v1/items/{item1['id']}/links/{link_id}")
    assert resp.status_code == 204

    # Verify gone
    resp = client.get(f"/api/v1/items/{item1['id']}/links")
    assert resp.status_code == 200
    assert len(resp.json()) == 0


def test_create_item_link_duplicate(client: TestClient):
    space = _create_space(client)
    item1 = client.post("/api/v1/items", json={"space_id": space["id"], "title": "A"}).json()
    item2 = client.post("/api/v1/items", json={"space_id": space["id"], "title": "B"}).json()

    client.post(f"/api/v1/items/{item1['id']}/links", json={"target_item_id": item2["id"]})
    resp = client.post(f"/api/v1/items/{item1['id']}/links", json={"target_item_id": item2["id"]})
    assert resp.status_code == 409


def test_create_item_link_self(client: TestClient):
    space = _create_space(client)
    item = client.post("/api/v1/items", json={"space_id": space["id"], "title": "Self"}).json()

    resp = client.post(f"/api/v1/items/{item['id']}/links", json={"target_item_id": item["id"]})
    assert resp.status_code == 422
