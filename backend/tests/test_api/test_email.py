"""API tests for email endpoints.

All Gmail API and auth calls are mocked to avoid real HTTP.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.openloop.db.models import DataSource, EmailCache
from backend.openloop.services import data_source_service
from contract.enums import SOURCE_TYPE_GMAIL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gmail_ds(db: Session) -> DataSource:
    """Create a system-level Gmail DataSource."""
    return data_source_service.create_data_source(
        db,
        space_id=None,
        name="Gmail",
        source_type=SOURCE_TYPE_GMAIL,
        config={
            "triage_labels": ["OL/Needs Response", "OL/FYI", "OL/Follow Up", "OL/Waiting", "OL/Agent Processed"],
            "sync_max_results": 50,
            "exclude_labels": ["SPAM", "TRASH"],
        },
    )


def _create_email(db: Session, gmail_message_id: str = "msg_1", **kwargs) -> EmailCache:
    """Insert an EmailCache row directly."""
    defaults = {
        "gmail_message_id": gmail_message_id,
        "gmail_thread_id": "thread_1",
        "subject": "Test Email",
        "from_address": "sender@example.com",
        "from_name": "Sender",
        "to_addresses": ["me@example.com"],
        "snippet": "This is a test email",
        "labels": ["INBOX", "UNREAD"],
        "is_unread": True,
        "received_at": datetime.now(UTC).replace(tzinfo=None),
    }
    defaults.update(kwargs)
    email = EmailCache(**defaults)
    db.add(email)
    db.commit()
    db.refresh(email)
    return email


# ---------------------------------------------------------------------------
# GET /api/v1/email/auth-status
# ---------------------------------------------------------------------------


@patch("backend.openloop.api.routes.email.gmail_client")
def test_auth_status_not_authenticated(mock_gmail, client: TestClient):
    mock_gmail.is_authenticated.return_value = False
    resp = client.get("/api/v1/email/auth-status")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is False


@patch("backend.openloop.api.routes.email.gmail_client")
def test_auth_status_authenticated(mock_gmail, client: TestClient):
    mock_gmail.is_authenticated.return_value = True
    resp = client.get("/api/v1/email/auth-status")
    assert resp.status_code == 200
    assert resp.json()["authenticated"] is True


# ---------------------------------------------------------------------------
# POST /api/v1/email/setup
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.email_integration_service.gmail_client")
def test_setup_creates_data_source(mock_gmail, client: TestClient, db_session: Session):
    mock_gmail.get_labels.return_value = []
    mock_gmail.create_label.return_value = {}
    mock_gmail.list_messages.return_value = []
    resp = client.post("/api/v1/email/setup", json={})
    assert resp.status_code == 201
    data = resp.json()
    assert data["source_type"] == SOURCE_TYPE_GMAIL
    assert data["space_id"] is None


# ---------------------------------------------------------------------------
# GET /api/v1/email/messages
# ---------------------------------------------------------------------------


def test_list_messages_empty(client: TestClient, db_session: Session):
    resp = client.get("/api/v1/email/messages")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_messages_with_data(client: TestClient, db_session: Session):
    _create_email(db_session, "msg_1", subject="Hello")
    _create_email(db_session, "msg_2", subject="World")
    resp = client.get("/api/v1/email/messages")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2


def test_list_messages_filter_unread(client: TestClient, db_session: Session):
    _create_email(db_session, "msg_1", is_unread=True)
    _create_email(db_session, "msg_2", is_unread=False, labels=["INBOX"])
    resp = client.get("/api/v1/email/messages", params={"unread_only": True})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1


def test_list_messages_pagination(client: TestClient, db_session: Session):
    for i in range(10):
        _create_email(db_session, f"msg_{i}", subject=f"Email {i}")
    resp = client.get("/api/v1/email/messages", params={"limit": 5})
    assert resp.status_code == 200
    assert len(resp.json()) == 5


# ---------------------------------------------------------------------------
# GET /api/v1/email/messages/{message_id}
# ---------------------------------------------------------------------------


@patch("backend.openloop.api.routes.email.gmail_client")
def test_get_message_with_body(mock_gmail, client: TestClient, db_session: Session):
    _create_email(db_session, "msg_detail")
    mock_gmail.get_message.return_value = {
        "id": "msg_detail",
        "threadId": "thread_1",
        "labelIds": ["INBOX"],
        "snippet": "Hello",
        "headers": {"from": "sender@example.com", "subject": "Test"},
        "body": "Full body text here",
        "attachments": [],
    }
    resp = client.get("/api/v1/email/messages/msg_detail")
    assert resp.status_code == 200
    data = resp.json()
    assert data["body"] == "Full body text here"


# ---------------------------------------------------------------------------
# POST /api/v1/email/messages/{id}/label
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.email_integration_service.gmail_client")
def test_label_message(mock_gmail, client: TestClient, db_session: Session):
    _create_email(db_session, "msg_lbl", labels=["INBOX", "UNREAD"])
    mock_gmail.modify_labels.return_value = {}
    resp = client.post(
        "/api/v1/email/messages/msg_lbl/label",
        json={"add_labels": ["OL/Needs Response"]},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "OL/Needs Response" in data["labels"]


# ---------------------------------------------------------------------------
# POST /api/v1/email/messages/{id}/archive
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.email_integration_service.gmail_client")
def test_archive_message(mock_gmail, client: TestClient, db_session: Session):
    _create_email(db_session, "msg_arc", labels=["INBOX", "UNREAD"])
    mock_gmail.archive_message.return_value = {}
    resp = client.post("/api/v1/email/messages/msg_arc/archive")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# POST /api/v1/email/messages/{id}/read
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.email_integration_service.gmail_client")
def test_mark_read(mock_gmail, client: TestClient, db_session: Session):
    _create_email(db_session, "msg_rd", labels=["INBOX", "UNREAD"], is_unread=True)
    mock_gmail.mark_as_read.return_value = {}
    resp = client.post("/api/v1/email/messages/msg_rd/read")
    assert resp.status_code == 204


# ---------------------------------------------------------------------------
# POST /api/v1/email/sync
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.email_integration_service.gmail_client")
def test_sync_endpoint(mock_gmail, client: TestClient, db_session: Session):
    ds = _make_gmail_ds(db_session)
    mock_gmail.list_messages.return_value = []
    resp = client.post("/api/v1/email/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert "added" in data
    assert "updated" in data


def test_sync_no_datasource(client: TestClient, db_session: Session):
    """Sync with no Gmail DataSource returns 404."""
    resp = client.post("/api/v1/email/sync")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/v1/email/stats
# ---------------------------------------------------------------------------


def test_stats_endpoint(client: TestClient, db_session: Session):
    _create_email(db_session, "msg_1", is_unread=True, labels=["INBOX", "UNREAD", "OL/Needs Response"])
    _create_email(db_session, "msg_2", is_unread=False, labels=["INBOX"])
    resp = client.get("/api/v1/email/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["unread_count"] == 1
    assert data["by_label"]["OL/Needs Response"] == 1


# ---------------------------------------------------------------------------
# POST /api/v1/email/drafts
# ---------------------------------------------------------------------------


@patch("backend.openloop.services.email_integration_service.gmail_client")
def test_create_draft(mock_gmail, client: TestClient, db_session: Session):
    mock_gmail.create_draft.return_value = {
        "id": "draft_1",
        "message": {"id": "msg_draft"},
    }
    resp = client.post(
        "/api/v1/email/drafts",
        json={
            "to": "recipient@example.com",
            "subject": "Hello",
            "body": "Hi there",
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["draft_id"] == "draft_1"
