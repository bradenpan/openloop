from fastapi.testclient import TestClient


def _create_agent(client: TestClient, name: str = "TestAgent", **kwargs) -> dict:
    payload = {"name": name, **kwargs}
    resp = client.post("/api/v1/agents", json=payload)
    assert resp.status_code == 201
    return resp.json()


def _create_space(client: TestClient, name: str = "Test Space", template: str = "project") -> dict:
    resp = client.post("/api/v1/spaces", json={"name": name, "template": template})
    assert resp.status_code == 201
    return resp.json()


def test_create_agent(client: TestClient):
    resp = client.post("/api/v1/agents", json={"name": "Odin"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Odin"
    assert data["default_model"] == "sonnet"
    assert data["status"] == "active"
    assert data["id"] is not None


def test_create_agent_with_details(client: TestClient):
    resp = client.post(
        "/api/v1/agents",
        json={
            "name": "Detailed",
            "description": "A detailed agent",
            "system_prompt": "You are helpful.",
            "default_model": "opus",
            "tools": ["search"],
            "mcp_tools": ["notion"],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["description"] == "A detailed agent"
    assert data["system_prompt"] == "You are helpful."
    assert data["default_model"] == "opus"
    assert data["tools"] == ["search"]
    assert data["mcp_tools"] == ["notion"]


def test_create_agent_with_spaces(client: TestClient):
    s1 = _create_space(client, name="S1")
    s2 = _create_space(client, name="S2")
    resp = client.post(
        "/api/v1/agents",
        json={"name": "Linked", "space_ids": [s1["id"], s2["id"]]},
    )
    assert resp.status_code == 201


def test_create_agent_duplicate_name(client: TestClient):
    client.post("/api/v1/agents", json={"name": "Unique"})
    resp = client.post("/api/v1/agents", json={"name": "Unique"})
    assert resp.status_code == 409


def test_list_agents_empty(client: TestClient):
    resp = client.get("/api/v1/agents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_agents(client: TestClient):
    _create_agent(client, name="A")
    _create_agent(client, name="B")
    resp = client.get("/api/v1/agents")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_agent(client: TestClient):
    agent = _create_agent(client, name="Fetch Me")
    resp = client.get(f"/api/v1/agents/{agent['id']}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Fetch Me"


def test_get_agent_not_found(client: TestClient):
    resp = client.get("/api/v1/agents/nonexistent")
    assert resp.status_code == 404


def test_update_agent(client: TestClient):
    agent = _create_agent(client, name="Old Name")
    resp = client.patch(f"/api/v1/agents/{agent['id']}", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_update_agent_partial(client: TestClient):
    agent = _create_agent(client, name="Partial", description="original")
    resp = client.patch(f"/api/v1/agents/{agent['id']}", json={"description": "changed"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["description"] == "changed"
    assert data["name"] == "Partial"


def test_update_agent_empty_body(client: TestClient):
    agent = _create_agent(client, name="NoOp")
    resp = client.patch(f"/api/v1/agents/{agent['id']}", json={})
    assert resp.status_code == 200
    assert resp.json()["name"] == "NoOp"


def test_update_agent_duplicate_name(client: TestClient):
    _create_agent(client, name="Taken")
    agent = _create_agent(client, name="Other")
    resp = client.patch(f"/api/v1/agents/{agent['id']}", json={"name": "Taken"})
    assert resp.status_code == 409


def test_update_agent_not_found(client: TestClient):
    resp = client.patch("/api/v1/agents/nonexistent", json={"name": "Nope"})
    assert resp.status_code == 404


def test_delete_agent(client: TestClient):
    agent = _create_agent(client, name="Delete Me")
    resp = client.delete(f"/api/v1/agents/{agent['id']}")
    assert resp.status_code == 204
    resp = client.get(f"/api/v1/agents/{agent['id']}")
    assert resp.status_code == 404


def test_delete_agent_not_found(client: TestClient):
    resp = client.delete("/api/v1/agents/nonexistent")
    assert resp.status_code == 404


# --- Permissions ---


def test_set_permission(client: TestClient):
    agent = _create_agent(client, name="Permed")
    resp = client.post(
        "/api/v1/agents/permissions",
        json={
            "agent_id": agent["id"],
            "resource_pattern": "spaces/*",
            "operation": "read",
            "grant_level": "always",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["agent_id"] == agent["id"]
    assert data["resource_pattern"] == "spaces/*"
    assert data["operation"] == "read"
    assert data["grant_level"] == "always"


def test_set_permission_upsert(client: TestClient):
    agent = _create_agent(client, name="Upsert")
    payload = {
        "agent_id": agent["id"],
        "resource_pattern": "spaces/*",
        "operation": "read",
        "grant_level": "always",
    }
    resp1 = client.post("/api/v1/agents/permissions", json=payload)
    payload["grant_level"] = "approval"
    resp2 = client.post("/api/v1/agents/permissions", json=payload)
    assert resp1.json()["id"] == resp2.json()["id"]
    assert resp2.json()["grant_level"] == "approval"


def test_get_permissions(client: TestClient):
    agent = _create_agent(client, name="WithPerms")
    client.post(
        "/api/v1/agents/permissions",
        json={
            "agent_id": agent["id"],
            "resource_pattern": "spaces/*",
            "operation": "read",
            "grant_level": "always",
        },
    )
    client.post(
        "/api/v1/agents/permissions",
        json={
            "agent_id": agent["id"],
            "resource_pattern": "items/*",
            "operation": "create",
            "grant_level": "approval",
        },
    )
    resp = client.get(f"/api/v1/agents/{agent['id']}/permissions")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_get_permissions_empty(client: TestClient):
    agent = _create_agent(client, name="NoPerms")
    resp = client.get(f"/api/v1/agents/{agent['id']}/permissions")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_permissions_agent_not_found(client: TestClient):
    resp = client.get("/api/v1/agents/nonexistent/permissions")
    assert resp.status_code == 404


def test_delete_permission(client: TestClient):
    agent = _create_agent(client, name="DelPerm")
    create_resp = client.post(
        "/api/v1/agents/permissions",
        json={
            "agent_id": agent["id"],
            "resource_pattern": "spaces/*",
            "operation": "read",
            "grant_level": "always",
        },
    )
    perm_id = create_resp.json()["id"]
    resp = client.delete(f"/api/v1/agents/permissions/{perm_id}")
    assert resp.status_code == 204
    # Verify gone
    perms = client.get(f"/api/v1/agents/{agent['id']}/permissions")
    assert len(perms.json()) == 0


def test_delete_permission_not_found(client: TestClient):
    resp = client.delete("/api/v1/agents/permissions/nonexistent")
    assert resp.status_code == 404
