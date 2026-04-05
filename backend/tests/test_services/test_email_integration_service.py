"""Unit tests for email_integration_service.

All Gmail API calls are mocked via unittest.mock.patch on
gmail_client functions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session

from backend.openloop.db.models import DataSource, EmailCache
from backend.openloop.services import (
    data_source_service,
    email_integration_service,
)
from contract.enums import SOURCE_TYPE_GMAIL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_gmail_ds(db: Session, **config_overrides) -> DataSource:
    """Create a system-level Gmail DataSource directly in the DB."""
    config = {
        "triage_labels": [
            "OL/Needs Response",
            "OL/FYI",
            "OL/Follow Up",
            "OL/Waiting",
            "OL/Agent Processed",
        ],
        "sync_max_results": 50,
        "exclude_labels": ["SPAM", "TRASH"],
    }
    config.update(config_overrides)
    return data_source_service.create_data_source(
        db,
        space_id=None,
        name="Gmail",
        source_type=SOURCE_TYPE_GMAIL,
        config=config,
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
# setup_email
# ---------------------------------------------------------------------------


class TestSetupEmail:
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_setup_email_creates_data_source(self, mock_gmail, db_session: Session):
        mock_gmail.get_labels.return_value = []
        mock_gmail.create_label.return_value = {}
        mock_gmail.list_messages.return_value = []
        ds = email_integration_service.setup_email(db_session)
        assert ds.source_type == SOURCE_TYPE_GMAIL
        assert ds.space_id is None
        assert ds.name == "Gmail"

    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_setup_email_idempotent(self, mock_gmail, db_session: Session):
        mock_gmail.get_labels.return_value = []
        mock_gmail.create_label.return_value = {}
        mock_gmail.list_messages.return_value = []
        ds1 = email_integration_service.setup_email(db_session)
        ds2 = email_integration_service.setup_email(db_session)
        assert ds1.id == ds2.id


# ---------------------------------------------------------------------------
# ensure_triage_labels
# ---------------------------------------------------------------------------


class TestEnsureTriageLabels:
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_creates_missing_labels(self, mock_gmail, db_session: Session):
        _make_gmail_ds(db_session)
        mock_gmail.get_labels.return_value = []
        mock_gmail.create_label.return_value = {}
        created = email_integration_service.ensure_triage_labels(db_session)
        assert len(created) == 5
        assert mock_gmail.create_label.call_count == 5

    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_skips_existing_labels(self, mock_gmail, db_session: Session):
        _make_gmail_ds(db_session)
        mock_gmail.get_labels.return_value = [
            {"name": "OL/Needs Response"},
            {"name": "OL/FYI"},
            {"name": "OL/Follow Up"},
            {"name": "OL/Waiting"},
            {"name": "OL/Agent Processed"},
        ]
        created = email_integration_service.ensure_triage_labels(db_session)
        assert len(created) == 0
        assert mock_gmail.create_label.call_count == 0


# ---------------------------------------------------------------------------
# sync_inbox
# ---------------------------------------------------------------------------


class TestSyncInbox:
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_adds_new_messages(self, mock_gmail, db_session: Session):
        ds = _make_gmail_ds(db_session)
        mock_gmail.list_messages.return_value = [
            {"id": "msg_a"},
            {"id": "msg_b"},
        ]
        mock_gmail.get_message_headers.side_effect = [
            {
                "id": "msg_a",
                "threadId": "thread_a",
                "labelIds": ["INBOX", "UNREAD"],
                "snippet": "Hello",
                "headers": {
                    "from": "Alice <alice@example.com>",
                    "to": "me@example.com",
                    "subject": "Subject A",
                    "date": "Mon, 1 Jan 2024 12:00:00 +0000",
                },
            },
            {
                "id": "msg_b",
                "threadId": "thread_b",
                "labelIds": ["INBOX"],
                "snippet": "World",
                "headers": {
                    "from": "Bob <bob@example.com>",
                    "to": "me@example.com",
                    "subject": "Subject B",
                    "date": "Mon, 1 Jan 2024 13:00:00 +0000",
                },
            },
        ]

        result = email_integration_service.sync_inbox(db_session, ds.id)
        assert result["added"] == 2
        assert result["updated"] == 0

        cached = db_session.query(EmailCache).all()
        assert len(cached) == 2

    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_updates_existing_messages(self, mock_gmail, db_session: Session):
        ds = _make_gmail_ds(db_session)
        _create_email(
            db_session,
            "msg_x",
            data_source_id=ds.id,
            labels=["INBOX", "UNREAD"],
            is_unread=True,
        )

        mock_gmail.list_messages.return_value = [{"id": "msg_x"}]
        mock_gmail.get_message_headers.return_value = {
            "id": "msg_x",
            "threadId": "thread_x",
            "labelIds": ["INBOX"],  # UNREAD removed
            "snippet": "Updated snippet",
            "headers": {
                "from": "Sender <sender@example.com>",
                "subject": "Test Email",
                "date": "Mon, 1 Jan 2024 12:00:00 +0000",
            },
        }

        result = email_integration_service.sync_inbox(db_session, ds.id)
        assert result["added"] == 0
        assert result["updated"] == 1

        updated = (
            db_session.query(EmailCache)
            .filter(EmailCache.gmail_message_id == "msg_x")
            .first()
        )
        assert updated.is_unread is False

    @patch("backend.openloop.services.email_integration_service.notification_service")
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_handles_refresh_error(self, mock_gmail, mock_notif, db_session: Session):
        ds = _make_gmail_ds(db_session)
        mock_gmail.list_messages.side_effect = RefreshError("token expired")

        result = email_integration_service.sync_inbox(db_session, ds.id)
        assert result == {"added": 0, "updated": 0}
        mock_notif.create_notification.assert_called_once()

    @patch("backend.openloop.services.email_integration_service.notification_service")
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_failure_tracking_creates_notification_at_threshold(
        self, mock_gmail, mock_notif, db_session: Session
    ):
        ds = _make_gmail_ds(db_session)
        resp = MagicMock()
        resp.status = 500
        mock_gmail.list_messages.side_effect = HttpError(resp, b"server error")

        # Reset failure counter for this DS
        email_integration_service._sync_failure_counts[ds.id] = 0

        # First 2 calls should not trigger notification
        for _ in range(2):
            email_integration_service.sync_inbox(db_session, ds.id)
        assert mock_notif.create_notification.call_count == 0

        # 3rd failure hits threshold
        email_integration_service.sync_inbox(db_session, ds.id)
        assert mock_notif.create_notification.call_count == 1

        # Clean up
        email_integration_service._sync_failure_counts.pop(ds.id, None)


# ---------------------------------------------------------------------------
# get_cached_messages
# ---------------------------------------------------------------------------


class TestGetCachedMessages:
    def test_basic_query(self, db_session: Session):
        _create_email(db_session, "msg_1", subject="First")
        _create_email(db_session, "msg_2", subject="Second")

        messages = email_integration_service.get_cached_messages(db_session)
        assert len(messages) == 2
        # Ordered by received_at DESC (most recent first)
        assert messages[0].subject in ("First", "Second")

    def test_filter_unread_only(self, db_session: Session):
        _create_email(db_session, "msg_1", is_unread=True)
        _create_email(db_session, "msg_2", is_unread=False, labels=["INBOX"])

        messages = email_integration_service.get_cached_messages(
            db_session, unread_only=True,
        )
        assert len(messages) == 1
        assert messages[0].gmail_message_id == "msg_1"

    def test_filter_by_label(self, db_session: Session):
        _create_email(db_session, "msg_1", labels=["INBOX", "OL/Needs Response"])
        _create_email(db_session, "msg_2", labels=["INBOX"])

        messages = email_integration_service.get_cached_messages(
            db_session, label="OL/Needs Response",
        )
        assert len(messages) == 1
        assert messages[0].gmail_message_id == "msg_1"

    def test_pagination(self, db_session: Session):
        for i in range(10):
            _create_email(db_session, f"msg_{i}", subject=f"Email {i}")

        messages = email_integration_service.get_cached_messages(
            db_session, limit=5,
        )
        assert len(messages) == 5


# ---------------------------------------------------------------------------
# get_inbox_stats
# ---------------------------------------------------------------------------


class TestGetInboxStats:
    def test_inbox_stats(self, db_session: Session):
        _create_email(
            db_session, "msg_1",
            is_unread=True,
            labels=["INBOX", "UNREAD", "OL/Needs Response"],
        )
        _create_email(
            db_session, "msg_2",
            is_unread=True,
            labels=["INBOX", "UNREAD", "OL/FYI"],
        )
        _create_email(
            db_session, "msg_3",
            is_unread=False,
            labels=["INBOX", "OL/Follow Up"],
        )

        stats = email_integration_service.get_inbox_stats(db_session)
        assert stats["unread_count"] == 2
        assert stats["by_label"]["OL/Needs Response"] == 1
        assert stats["by_label"]["OL/FYI"] == 1
        assert stats["by_label"]["OL/Follow Up"] == 1
        assert stats["by_label"]["OL/Waiting"] == 0
        assert stats["oldest_unread"] is not None


# ---------------------------------------------------------------------------
# label_message
# ---------------------------------------------------------------------------


class TestLabelMessage:
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_label_message(self, mock_gmail, db_session: Session):
        _create_email(db_session, "msg_lbl", labels=["INBOX", "UNREAD"])
        mock_gmail.modify_labels.return_value = {}

        cached = email_integration_service.label_message(
            db_session,
            "msg_lbl",
            add_labels=["OL/Needs Response"],
            remove_labels=["UNREAD"],
        )
        assert "OL/Needs Response" in cached.labels
        assert "UNREAD" not in cached.labels
        mock_gmail.modify_labels.assert_called_once()


# ---------------------------------------------------------------------------
# archive_message
# ---------------------------------------------------------------------------


class TestArchiveMessage:
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_archive_message(self, mock_gmail, db_session: Session):
        _create_email(db_session, "msg_arc", labels=["INBOX", "UNREAD"])
        mock_gmail.archive_message.return_value = {}

        cached = email_integration_service.archive_message(db_session, "msg_arc")
        assert "INBOX" not in cached.labels
        mock_gmail.archive_message.assert_called_once_with("msg_arc")


# ---------------------------------------------------------------------------
# mark_read
# ---------------------------------------------------------------------------


class TestMarkRead:
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_mark_read(self, mock_gmail, db_session: Session):
        _create_email(db_session, "msg_rd", labels=["INBOX", "UNREAD"], is_unread=True)
        mock_gmail.mark_as_read.return_value = {}

        cached = email_integration_service.mark_read(db_session, "msg_rd")
        assert cached.is_unread is False
        assert "UNREAD" not in cached.labels
        mock_gmail.mark_as_read.assert_called_once_with("msg_rd")


# ---------------------------------------------------------------------------
# Draft / Send operations
# ---------------------------------------------------------------------------


class TestDraftOperations:
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_create_draft(self, mock_gmail, db_session: Session):
        mock_gmail.create_draft.return_value = {
            "id": "draft_1",
            "message": {"id": "msg_draft_1"},
        }
        result = email_integration_service.create_draft(
            db_session, to="recipient@example.com", subject="Hello", body="Hi there",
        )
        assert result["id"] == "draft_1"
        mock_gmail.create_draft.assert_called_once()

    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_send_draft(self, mock_gmail, db_session: Session):
        mock_gmail.send_draft.return_value = {
            "id": "msg_sent",
            "threadId": "thread_sent",
        }
        result = email_integration_service.send_draft(db_session, "draft_1")
        assert result["id"] == "msg_sent"
        mock_gmail.send_draft.assert_called_once_with("draft_1")

    @patch("backend.openloop.services.email_integration_service.gmail_client")
    def test_send_reply(self, mock_gmail, db_session: Session):
        mock_gmail.send_reply.return_value = {
            "id": "msg_reply",
            "threadId": "thread_reply",
        }
        result = email_integration_service.send_reply(
            db_session, "msg_original", "Thanks!",
        )
        assert result["id"] == "msg_reply"
        mock_gmail.send_reply.assert_called_once_with("msg_original", "Thanks!")
