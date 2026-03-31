from fastapi.testclient import TestClient


def test_create_space(client: TestClient):
    resp = client.post(
        "/api/v1/spaces",
        json={"name": "Test Project", "template": "project"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test Project"
    assert data["template"] == "project"
    assert data["board_enabled"] is True
    assert data["id"] is not None


def test_create_space_with_description(client: TestClient):
    resp = client.post(
        "/api/v1/spaces",
        json={"name": "Described", "template": "simple", "description": "A simple space"},
    )
    assert resp.status_code == 201
    assert resp.json()["description"] == "A simple space"


def test_create_space_duplicate(client: TestClient):
    client.post("/api/v1/spaces", json={"name": "Dup", "template": "simple"})
    resp = client.post("/api/v1/spaces", json={"name": "Dup", "template": "simple"})
    assert resp.status_code == 409


def test_create_space_invalid_template(client: TestClient):
    resp = client.post("/api/v1/spaces", json={"name": "Bad", "template": "fake"})
    assert resp.status_code == 422


def test_list_spaces_empty(client: TestClient):
    resp = client.get("/api/v1/spaces")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_spaces(client: TestClient):
    client.post("/api/v1/spaces", json={"name": "A", "template": "simple"})
    client.post("/api/v1/spaces", json={"name": "B", "template": "project"})
    resp = client.get("/api/v1/spaces")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_space(client: TestClient):
    create_resp = client.post("/api/v1/spaces", json={"name": "Get Me", "template": "crm"})
    space_id = create_resp.json()["id"]
    resp = client.get(f"/api/v1/spaces/{space_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Get Me"


def test_get_space_not_found(client: TestClient):
    resp = client.get("/api/v1/spaces/nonexistent")
    assert resp.status_code == 404


def test_update_space(client: TestClient):
    create_resp = client.post("/api/v1/spaces", json={"name": "Update Me", "template": "project"})
    space_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/spaces/{space_id}", json={"name": "Updated"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated"


def test_update_space_partial(client: TestClient):
    create_resp = client.post(
        "/api/v1/spaces",
        json={"name": "Partial Update", "template": "project", "description": "original"},
    )
    space_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/spaces/{space_id}", json={"description": "changed"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["description"] == "changed"
    assert data["name"] == "Partial Update"


def test_update_space_clear_description(client: TestClient):
    """Setting description to null should clear it, not be ignored."""
    create_resp = client.post(
        "/api/v1/spaces",
        json={"name": "Clear Test", "template": "simple", "description": "has desc"},
    )
    space_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/spaces/{space_id}", json={"description": None})
    assert resp.status_code == 200
    assert resp.json()["description"] is None


def test_update_space_empty_body(client: TestClient):
    """Empty PATCH body should be a no-op."""
    create_resp = client.post("/api/v1/spaces", json={"name": "NoOp Test", "template": "simple"})
    space_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/spaces/{space_id}", json={})
    assert resp.status_code == 200
    assert resp.json()["name"] == "NoOp Test"


def test_update_space_not_found(client: TestClient):
    resp = client.patch("/api/v1/spaces/nonexistent", json={"name": "Nope"})
    assert resp.status_code == 404


def test_delete_space(client: TestClient):
    create_resp = client.post("/api/v1/spaces", json={"name": "Delete Me", "template": "simple"})
    space_id = create_resp.json()["id"]
    resp = client.delete(f"/api/v1/spaces/{space_id}")
    assert resp.status_code == 204
    # Verify it's gone
    resp = client.get(f"/api/v1/spaces/{space_id}")
    assert resp.status_code == 404


def test_delete_space_not_found(client: TestClient):
    resp = client.delete("/api/v1/spaces/nonexistent")
    assert resp.status_code == 404
