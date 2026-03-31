from fastapi.testclient import TestClient


def _make_space(client: TestClient, name: str = "Doc Space") -> dict:
    resp = client.post(
        "/api/v1/spaces",
        json={"name": name, "template": "project"},
    )
    assert resp.status_code == 201
    return resp.json()


def _make_document(client: TestClient, space_id: str, title: str = "Test Doc") -> dict:
    resp = client.post(
        "/api/v1/documents",
        json={"space_id": space_id, "title": title},
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_document(client: TestClient):
    space = _make_space(client)
    resp = client.post(
        "/api/v1/documents",
        json={"space_id": space["id"], "title": "My Doc"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "My Doc"
    assert data["source"] == "local"
    assert data["space_id"] == space["id"]


def test_create_document_invalid_space(client: TestClient):
    resp = client.post(
        "/api/v1/documents",
        json={"space_id": "nonexistent", "title": "Bad"},
    )
    assert resp.status_code == 404


def test_create_document_with_tags(client: TestClient):
    space = _make_space(client)
    resp = client.post(
        "/api/v1/documents",
        json={
            "space_id": space["id"],
            "title": "Tagged",
            "tags": ["design", "v2"],
        },
    )
    assert resp.status_code == 201
    assert resp.json()["tags"] == ["design", "v2"]


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_documents_empty(client: TestClient):
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_documents(client: TestClient):
    space = _make_space(client)
    _make_document(client, space["id"], "A")
    _make_document(client, space["id"], "B")
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_documents_filter_by_space(client: TestClient):
    s1 = _make_space(client, "S1")
    s2 = _make_space(client, "S2")
    _make_document(client, s1["id"], "D1")
    _make_document(client, s2["id"], "D2")
    resp = client.get("/api/v1/documents", params={"space_id": s1["id"]})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "D1"


def test_list_documents_search(client: TestClient):
    space = _make_space(client)
    _make_document(client, space["id"], "Architecture Guide")
    _make_document(client, space["id"], "Setup Notes")
    resp = client.get("/api/v1/documents", params={"search": "architecture"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["title"] == "Architecture Guide"


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_document(client: TestClient):
    space = _make_space(client)
    doc = _make_document(client, space["id"])
    resp = client.get(f"/api/v1/documents/{doc['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == doc["id"]


def test_get_document_not_found(client: TestClient):
    resp = client.get("/api/v1/documents/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_document(client: TestClient):
    space = _make_space(client)
    doc = _make_document(client, space["id"])
    resp = client.delete(f"/api/v1/documents/{doc['id']}")
    assert resp.status_code == 204
    # Verify deleted
    resp = client.get(f"/api/v1/documents/{doc['id']}")
    assert resp.status_code == 404


def test_delete_document_not_found(client: TestClient):
    resp = client.delete("/api/v1/documents/nonexistent")
    assert resp.status_code == 404
