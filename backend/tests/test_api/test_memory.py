from fastapi.testclient import TestClient


def _make_entry(
    client: TestClient,
    namespace: str = "test",
    key: str = "k1",
    value: str = "v1",
) -> dict:
    resp = client.post(
        "/api/v1/memory",
        json={"namespace": namespace, "key": key, "value": value},
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_entry(client: TestClient):
    resp = client.post(
        "/api/v1/memory",
        json={"namespace": "prefs", "key": "theme", "value": "dark"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["namespace"] == "prefs"
    assert data["key"] == "theme"
    assert data["value"] == "dark"
    assert data["source"] == "user"


def test_create_entry_duplicate(client: TestClient):
    _make_entry(client, namespace="ns", key="dup")
    resp = client.post(
        "/api/v1/memory",
        json={"namespace": "ns", "key": "dup", "value": "v2"},
    )
    assert resp.status_code == 409


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_entries_empty(client: TestClient):
    resp = client.get("/api/v1/memory")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_entries(client: TestClient):
    _make_entry(client, key="a")
    _make_entry(client, key="b")
    resp = client.get("/api/v1/memory")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_entries_filter_namespace(client: TestClient):
    _make_entry(client, namespace="alpha", key="x")
    _make_entry(client, namespace="beta", key="y")
    resp = client.get("/api/v1/memory", params={"namespace": "alpha"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["namespace"] == "alpha"


def test_list_entries_search(client: TestClient):
    _make_entry(client, key="favorite_color", value="blue")
    _make_entry(client, key="name", value="Alice")
    resp = client.get("/api/v1/memory", params={"search": "color"})
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_entry(client: TestClient):
    entry = _make_entry(client)
    resp = client.get(f"/api/v1/memory/{entry['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == entry["id"]


def test_get_entry_not_found(client: TestClient):
    resp = client.get("/api/v1/memory/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_entry(client: TestClient):
    entry = _make_entry(client, value="old")
    resp = client.patch(
        f"/api/v1/memory/{entry['id']}",
        json={"value": "new"},
    )
    assert resp.status_code == 200
    assert resp.json()["value"] == "new"


def test_update_entry_not_found(client: TestClient):
    resp = client.patch(
        "/api/v1/memory/nonexistent",
        json={"value": "x"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_entry(client: TestClient):
    entry = _make_entry(client)
    resp = client.delete(f"/api/v1/memory/{entry['id']}")
    assert resp.status_code == 204
    resp = client.get(f"/api/v1/memory/{entry['id']}")
    assert resp.status_code == 404


def test_delete_entry_not_found(client: TestClient):
    resp = client.delete("/api/v1/memory/nonexistent")
    assert resp.status_code == 404
