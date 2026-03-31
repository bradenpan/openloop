from fastapi.testclient import TestClient


def _create_space(client: TestClient, name: str = "Test Space", template: str = "project") -> dict:
    resp = client.post("/api/v1/spaces", json={"name": name, "template": template})
    assert resp.status_code == 201
    return resp.json()


def test_create_todo(client: TestClient):
    space = _create_space(client)
    resp = client.post(
        "/api/v1/todos",
        json={"space_id": space["id"], "title": "Buy milk"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Buy milk"
    assert data["space_id"] == space["id"]
    assert data["is_done"] is False
    assert data["id"] is not None


def test_create_todo_with_due_date(client: TestClient):
    space = _create_space(client)
    resp = client.post(
        "/api/v1/todos",
        json={"space_id": space["id"], "title": "Deadline", "due_date": "2026-04-15T00:00:00Z"},
    )
    assert resp.status_code == 201
    assert resp.json()["due_date"] is not None


def test_create_todo_space_not_found(client: TestClient):
    resp = client.post(
        "/api/v1/todos",
        json={"space_id": "nonexistent", "title": "Orphan"},
    )
    assert resp.status_code == 404


def test_list_todos_empty(client: TestClient):
    resp = client.get("/api/v1/todos")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_todos(client: TestClient):
    space = _create_space(client)
    client.post("/api/v1/todos", json={"space_id": space["id"], "title": "A"})
    client.post("/api/v1/todos", json={"space_id": space["id"], "title": "B"})
    resp = client.get("/api/v1/todos")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_todos_filter_by_space(client: TestClient):
    s1 = _create_space(client, name="S1")
    s2 = _create_space(client, name="S2")
    client.post("/api/v1/todos", json={"space_id": s1["id"], "title": "In S1"})
    client.post("/api/v1/todos", json={"space_id": s2["id"], "title": "In S2"})
    resp = client.get(f"/api/v1/todos?space_id={s1['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "In S1"


def test_list_todos_filter_by_is_done(client: TestClient):
    space = _create_space(client)
    client.post("/api/v1/todos", json={"space_id": space["id"], "title": "Open"})
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "Done"})
    todo_id = create_resp.json()["id"]
    client.patch(f"/api/v1/todos/{todo_id}", json={"is_done": True})
    resp = client.get("/api/v1/todos?is_done=false")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Open"


def test_get_todo(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "Fetch Me"})
    todo_id = create_resp.json()["id"]
    resp = client.get(f"/api/v1/todos/{todo_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Fetch Me"


def test_get_todo_not_found(client: TestClient):
    resp = client.get("/api/v1/todos/nonexistent")
    assert resp.status_code == 404


def test_update_todo(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "Old"})
    todo_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/todos/{todo_id}", json={"title": "New"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "New"


def test_update_todo_mark_done(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "Task"})
    todo_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/todos/{todo_id}", json={"is_done": True})
    assert resp.status_code == 200
    assert resp.json()["is_done"] is True


def test_update_todo_partial(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "Partial"})
    todo_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/todos/{todo_id}", json={"is_done": True})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_done"] is True
    assert data["title"] == "Partial"  # unchanged


def test_update_todo_empty_body(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "NoOp"})
    todo_id = create_resp.json()["id"]
    resp = client.patch(f"/api/v1/todos/{todo_id}", json={})
    assert resp.status_code == 200
    assert resp.json()["title"] == "NoOp"


def test_update_todo_not_found(client: TestClient):
    resp = client.patch("/api/v1/todos/nonexistent", json={"title": "Nope"})
    assert resp.status_code == 404


def test_delete_todo(client: TestClient):
    space = _create_space(client)
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "Delete Me"})
    todo_id = create_resp.json()["id"]
    resp = client.delete(f"/api/v1/todos/{todo_id}")
    assert resp.status_code == 204
    # Verify gone
    resp = client.get(f"/api/v1/todos/{todo_id}")
    assert resp.status_code == 404


def test_delete_todo_not_found(client: TestClient):
    resp = client.delete("/api/v1/todos/nonexistent")
    assert resp.status_code == 404


def test_promote_todo(client: TestClient):
    space = _create_space(client, template="project")
    create_resp = client.post(
        "/api/v1/todos", json={"space_id": space["id"], "title": "Promote Me"}
    )
    todo_id = create_resp.json()["id"]
    resp = client.post(f"/api/v1/todos/{todo_id}/promote", json={})
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Promote Me"
    assert data["item_type"] == "task"
    assert data["space_id"] == space["id"]


def test_promote_todo_with_stage(client: TestClient):
    space = _create_space(client, template="project")
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "Staged"})
    todo_id = create_resp.json()["id"]
    resp = client.post(f"/api/v1/todos/{todo_id}/promote", json={"stage": "in_progress"})
    assert resp.status_code == 201
    assert resp.json()["stage"] == "in_progress"


def test_promote_todo_already_promoted(client: TestClient):
    space = _create_space(client, template="project")
    create_resp = client.post(
        "/api/v1/todos", json={"space_id": space["id"], "title": "Double Promote"}
    )
    todo_id = create_resp.json()["id"]
    client.post(f"/api/v1/todos/{todo_id}/promote", json={})
    resp = client.post(f"/api/v1/todos/{todo_id}/promote", json={})
    assert resp.status_code == 409


def test_promote_todo_no_board(client: TestClient):
    space = _create_space(client, name="Simple", template="simple")
    create_resp = client.post("/api/v1/todos", json={"space_id": space["id"], "title": "No Board"})
    todo_id = create_resp.json()["id"]
    resp = client.post(f"/api/v1/todos/{todo_id}/promote", json={})
    assert resp.status_code == 422


def test_promote_todo_not_found(client: TestClient):
    resp = client.post("/api/v1/todos/nonexistent/promote", json={})
    assert resp.status_code == 404
