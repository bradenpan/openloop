"""Tests for GET /api/v1/system/backup-status."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.openloop.main import app


def _make_client():
    """Create a test client (no DB dependency needed for this route)."""
    return TestClient(app)


def test_backup_status_no_file():
    """When .last_backup doesn't exist, needs_backup should be True."""
    with patch(
        "backend.openloop.api.routes.system._LAST_BACKUP_PATH"
    ) as mock_path:
        mock_path.exists.return_value = False
        client = _make_client()
        resp = client.get("/api/v1/system/backup-status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["last_backup_at"] is None
    assert data["hours_since_backup"] is None
    assert data["needs_backup"] is True


def test_backup_status_recent():
    """When .last_backup is recent (<24h), needs_backup should be False."""
    recent_ts = datetime.now(UTC).isoformat()

    with patch(
        "backend.openloop.api.routes.system._LAST_BACKUP_PATH"
    ) as mock_path:
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = recent_ts
        client = _make_client()
        resp = client.get("/api/v1/system/backup-status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["last_backup_at"] == recent_ts
    assert data["hours_since_backup"] == 0
    assert data["needs_backup"] is False


def test_backup_status_old():
    """When .last_backup is >24h old, needs_backup should be True."""
    old_ts = (datetime.now(UTC) - timedelta(hours=48)).isoformat()

    with patch(
        "backend.openloop.api.routes.system._LAST_BACKUP_PATH"
    ) as mock_path:
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = old_ts
        client = _make_client()
        resp = client.get("/api/v1/system/backup-status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["last_backup_at"] == old_ts
    assert data["hours_since_backup"] >= 47  # allow for test execution time
    assert data["needs_backup"] is True


def test_backup_status_hours_calculation():
    """Verify hours_since_backup is calculated correctly."""
    ts = (datetime.now(UTC) - timedelta(hours=6, minutes=30)).isoformat()

    with patch(
        "backend.openloop.api.routes.system._LAST_BACKUP_PATH"
    ) as mock_path:
        mock_path.exists.return_value = True
        mock_path.read_text.return_value = ts
        client = _make_client()
        resp = client.get("/api/v1/system/backup-status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["hours_since_backup"] == 6
    assert data["needs_backup"] is False
