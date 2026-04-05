from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _make_space(client: TestClient, name: str = "DS Space") -> dict:
    resp = client.post(
        "/api/v1/spaces",
        json={"name": name, "template": "project"},
    )
    assert resp.status_code == 201
    return resp.json()


def _make_data_source(
    client: TestClient,
    space_id: str,
    name: str = "Test DS",
    source_type: str = "local",
) -> dict:
    resp = client.post(
        "/api/v1/data-sources",
        json={"space_id": space_id, "name": name, "source_type": source_type},
    )
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_data_source(client: TestClient):
    space = _make_space(client)
    resp = client.post(
        "/api/v1/data-sources",
        json={"space_id": space["id"], "name": "My DS", "source_type": "google_drive"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "My DS"
    assert data["source_type"] == "google_drive"
    assert data["status"] == "active"


def test_create_data_source_invalid_space(client: TestClient):
    resp = client.post(
        "/api/v1/data-sources",
        json={"space_id": "nonexistent", "name": "Bad", "source_type": "local"},
    )
    assert resp.status_code == 404


def test_create_data_source_missing_fields(client: TestClient):
    """Missing required fields should return 422."""
    resp = client.post("/api/v1/data-sources", json={"name": "Bad"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------


def test_list_data_sources_empty(client: TestClient):
    resp = client.get("/api/v1/data-sources")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_data_sources(client: TestClient):
    space = _make_space(client)
    _make_data_source(client, space["id"], "A")
    _make_data_source(client, space["id"], "B")
    resp = client.get("/api/v1/data-sources")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


def test_list_data_sources_filter_by_space(client: TestClient):
    s1 = _make_space(client, "S1")
    s2 = _make_space(client, "S2")
    _make_data_source(client, s1["id"], "DS1")
    _make_data_source(client, s2["id"], "DS2")
    resp = client.get("/api/v1/data-sources", params={"space_id": s1["id"]})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "DS1"


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------


def test_get_data_source(client: TestClient):
    space = _make_space(client)
    ds = _make_data_source(client, space["id"])
    resp = client.get(f"/api/v1/data-sources/{ds['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == ds["id"]


def test_get_data_source_not_found(client: TestClient):
    resp = client.get("/api/v1/data-sources/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_data_source(client: TestClient):
    space = _make_space(client)
    ds = _make_data_source(client, space["id"], "Old Name")
    resp = client.patch(
        f"/api/v1/data-sources/{ds['id']}",
        json={"name": "New Name"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"


def test_update_data_source_not_found(client: TestClient):
    resp = client.patch(
        "/api/v1/data-sources/nonexistent",
        json={"name": "X"},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_data_source(client: TestClient):
    space = _make_space(client)
    ds = _make_data_source(client, space["id"])
    resp = client.delete(f"/api/v1/data-sources/{ds['id']}")
    assert resp.status_code == 204
    resp = client.get(f"/api/v1/data-sources/{ds['id']}")
    assert resp.status_code == 404


def test_delete_data_source_not_found(client: TestClient):
    resp = client.delete("/api/v1/data-sources/nonexistent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# System query filter
# ---------------------------------------------------------------------------


def test_list_data_sources_system_true(client: TestClient, db_session: Session):
    """GET /data-sources?system=true returns only system sources."""
    from backend.openloop.services import data_source_service

    space = _make_space(client)
    # Create a space-bound source via API
    _make_data_source(client, space["id"], "Space DS")
    # Create a system-level source directly (API requires space_id)
    data_source_service.create_data_source(
        db_session, space_id=None, name="System DS", source_type="google_calendar"
    )

    resp = client.get("/api/v1/data-sources", params={"system": True})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "System DS"
    assert data[0]["space_id"] is None


# ---------------------------------------------------------------------------
# Exclude / Include
# ---------------------------------------------------------------------------


def test_exclude_data_source(client: TestClient, db_session: Session):
    """POST /data-sources/{id}/exclude creates an exclusion."""
    from backend.openloop.services import data_source_service

    space = _make_space(client)
    ds = data_source_service.create_data_source(
        db_session, space_id=None, name="Cal", source_type="google_calendar"
    )

    resp = client.post(
        f"/api/v1/data-sources/{ds.id}/exclude",
        json={"space_id": space["id"]},
    )
    assert resp.status_code == 204


def test_include_data_source(client: TestClient, db_session: Session):
    """DELETE /data-sources/{id}/exclude removes the exclusion."""
    from backend.openloop.services import data_source_service

    space = _make_space(client)
    ds = data_source_service.create_data_source(
        db_session, space_id=None, name="Cal", source_type="google_calendar"
    )
    # Exclude first
    data_source_service.exclude_from_space(db_session, space["id"], ds.id)

    resp = client.delete(
        f"/api/v1/data-sources/{ds.id}/exclude",
        params={"space_id": space["id"]},
    )
    assert resp.status_code == 204


def test_exclude_rejects_space_level_source(client: TestClient, db_session: Session):
    """Excluding a space-bound source should return 422."""
    space = _make_space(client)
    ds = _make_data_source(client, space["id"], "Local DS")

    resp = client.post(
        f"/api/v1/data-sources/{ds['id']}/exclude",
        json={"space_id": space["id"]},
    )
    assert resp.status_code == 422


def test_exclude_nonexistent_ds(client: TestClient):
    """Excluding a nonexistent data source returns 404."""
    space = _make_space(client)
    resp = client.post(
        "/api/v1/data-sources/nonexistent-id/exclude",
        json={"space_id": space["id"]},
    )
    assert resp.status_code == 404
