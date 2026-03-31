from fastapi.testclient import TestClient


def _make_agent(client: TestClient, name: str = "ConvAgent") -> dict:
    resp = client.post(
        "/api/v1/agents",
        json={"name": name},
    )
    assert resp.status_code == 201
    return resp.json()


def _make_space(client: TestClient, name: str = "Conv Space") -> dict:
    resp = client.post(
        "/api/v1/spaces",
        json={"name": name, "template": "simple"},
    )
    assert resp.status_code == 201
    return resp.json()


def _make_conversation(
    client: TestClient,
    agent_id: str,
    space_id: str | None = None,
    name: str = "Test Conv",
) -> dict:
    body = {"agent_id": agent_id, "name": name}
    if space_id:
        body["space_id"] = space_id
    resp = client.post("/api/v1/conversations", json=body)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_conversation(client: TestClient):
    agent = _make_agent(client)
    resp = client.post(
        "/api/v1/conversations",
        json={"agent_id": agent["id"], "name": "My Conv"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My Conv"
    assert data["agent_id"] == agent["id"]
    assert data["status"] == "active"


def test_create_conversation_invalid_agent(client: TestClient):
    resp = client.post(
        "/api/v1/conversations",
        json={"agent_id": "nonexistent", "name": "Bad"},
    )
    assert resp.status_code == 404


def test_create_conversation_with_space(client: TestClient):
    agent = _make_agent(client)
    space = _make_space(client)
    resp = client.post(
        "/api/v1/conversations",
        json={"agent_id": agent["id"], "name": "Spaced", "space_id": space["id"]},
    )
    assert resp.status_code == 201
    assert resp.json()["space_id"] == space["id"]


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_conversations_empty(client: TestClient):
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_conversations(client: TestClient):
    agent = _make_agent(client)
    _make_conversation(client, agent["id"], name="Conv1")
    _make_conversation(client, agent["id"], name="Conv2")
    resp = client.get("/api/v1/conversations")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_conversations_filter_by_status(client: TestClient):
    agent = _make_agent(client)
    conv = _make_conversation(client, agent["id"], name="ToClose")
    client.post(f"/api/v1/conversations/{conv['id']}/close")
    _make_conversation(client, agent["id"], name="StillActive")
    resp = client.get("/api/v1/conversations", params={"status": "active"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "StillActive"


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_conversation(client: TestClient):
    agent = _make_agent(client)
    conv = _make_conversation(client, agent["id"])
    resp = client.get(f"/api/v1/conversations/{conv['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == conv["id"]


def test_get_conversation_not_found(client: TestClient):
    resp = client.get("/api/v1/conversations/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Close / Reopen
# ---------------------------------------------------------------------------


def test_close_conversation(client: TestClient):
    agent = _make_agent(client)
    conv = _make_conversation(client, agent["id"])
    resp = client.post(f"/api/v1/conversations/{conv['id']}/close")
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


def test_close_already_closed(client: TestClient):
    agent = _make_agent(client)
    conv = _make_conversation(client, agent["id"])
    client.post(f"/api/v1/conversations/{conv['id']}/close")
    resp = client.post(f"/api/v1/conversations/{conv['id']}/close")
    assert resp.status_code == 409


def test_reopen_conversation(client: TestClient):
    agent = _make_agent(client)
    conv = _make_conversation(client, agent["id"])
    client.post(f"/api/v1/conversations/{conv['id']}/close")
    resp = client.post(f"/api/v1/conversations/{conv['id']}/reopen")
    assert resp.status_code == 200
    assert resp.json()["status"] == "active"


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


def test_get_messages_empty(client: TestClient):
    agent = _make_agent(client)
    conv = _make_conversation(client, agent["id"])
    resp = client.get(f"/api/v1/conversations/{conv['id']}/messages")
    assert resp.status_code == 200
    assert resp.json() == []
