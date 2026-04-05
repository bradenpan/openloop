"""Tests for Email MCP tool functions and context assembly.

Tests call the async tool functions directly with a test DB session injected
via the _db parameter. Permission mapping tests verify the _MCP_TOOL_MAP
entries.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import insert
from sqlalchemy.orm import Session

from backend.openloop.agents.mcp_tools import (
    archive_email,
    draft_email,
    get_email,
    get_email_headers,
    get_inbox_stats,
    label_email,
    list_emails,
    mark_email_read,
    send_email,
    send_reply,
)
from backend.openloop.db.models import DataSource, EmailCache, Space, space_data_source_exclusions
from backend.openloop.services import data_source_service
from contract.enums import SOURCE_TYPE_GMAIL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(result: str) -> dict:
    """Parse a tool's JSON string return value."""
    return json.loads(result)


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
        "synced_at": datetime.now(UTC).replace(tzinfo=None),
    }
    defaults.update(kwargs)
    email = EmailCache(**defaults)
    db.add(email)
    db.commit()
    db.refresh(email)
    return email


def _make_space(db: Session, name: str = "Test Space") -> Space:
    space = Space(name=name, template="project")
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


# ---------------------------------------------------------------------------
# Read tools
# ---------------------------------------------------------------------------


class TestListEmails:
    @pytest.mark.asyncio
    async def test_list_emails_from_cache(self, db_session: Session):
        _create_email(db_session, "msg_1", subject="Hello")
        _create_email(db_session, "msg_2", subject="World")

        result = _parse(await list_emails(_db=db_session))
        assert "result" in result
        assert len(result["result"]) == 2

    @pytest.mark.asyncio
    async def test_list_emails_empty(self, db_session: Session):
        result = _parse(await list_emails(_db=db_session))
        assert "result" in result
        assert len(result["result"]) == 0


class TestGetEmail:
    @pytest.mark.asyncio
    @patch("backend.openloop.agents.mcp_tools.gmail_client")
    async def test_get_email_live_fetch(self, mock_gmail, db_session: Session):
        mock_gmail.get_message.return_value = {
            "id": "msg_live",
            "threadId": "thread_live",
            "labelIds": ["INBOX"],
            "snippet": "Hello",
            "headers": {"from": "sender@example.com", "subject": "Test"},
            "body": "Full body text here",
            "attachments": [],
            "gmail_link": "https://mail.google.com/mail/u/0/#inbox/msg_live",
        }

        result = _parse(await get_email(message_id="msg_live", _db=db_session))
        assert "result" in result
        assert result["result"]["body"] == "Full body text here"
        mock_gmail.get_message.assert_called_once_with("msg_live")


class TestGetEmailHeaders:
    @pytest.mark.asyncio
    async def test_get_email_headers_from_cache(self, db_session: Session):
        _create_email(
            db_session, "msg_hdr",
            subject="Header Test",
            from_name="Alice",
            from_address="alice@example.com",
        )

        result = _parse(await get_email_headers(message_id="msg_hdr", _db=db_session))
        assert "result" in result
        assert result["result"]["subject"] == "Header Test"
        assert result["result"]["from_name"] == "Alice"
        assert result["result"]["from_address"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_get_email_headers_not_found(self, db_session: Session):
        result = _parse(await get_email_headers(message_id="nonexistent", _db=db_session))
        assert result["is_error"] is True


class TestGetInboxStats:
    @pytest.mark.asyncio
    async def test_get_inbox_stats_tool(self, db_session: Session):
        _create_email(
            db_session, "msg_1",
            is_unread=True,
            labels=["INBOX", "UNREAD", "OL/Needs Response"],
        )
        _create_email(
            db_session, "msg_2",
            is_unread=False,
            labels=["INBOX"],
        )

        result = _parse(await get_inbox_stats(_db=db_session))
        assert "result" in result
        assert result["result"]["unread_count"] == 1
        assert result["result"]["by_label"]["OL/Needs Response"] == 1


# ---------------------------------------------------------------------------
# Edit tools
# ---------------------------------------------------------------------------


class TestLabelEmail:
    @pytest.mark.asyncio
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    async def test_label_email_tool(self, mock_gmail, db_session: Session):
        _create_email(db_session, "msg_lbl", labels=["INBOX", "UNREAD"])
        mock_gmail.modify_labels.return_value = {}

        result = _parse(await label_email(
            message_id="msg_lbl",
            add_labels="OL/Needs Response",
            _db=db_session,
        ))
        assert "result" in result
        assert "OL/Needs Response" in result["result"]["labels"]


class TestArchiveEmail:
    @pytest.mark.asyncio
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    async def test_archive_email_tool(self, mock_gmail, db_session: Session):
        _create_email(db_session, "msg_arc", labels=["INBOX", "UNREAD"])
        mock_gmail.archive_message.return_value = {}

        result = _parse(await archive_email(message_id="msg_arc", _db=db_session))
        assert "result" in result
        assert result["result"]["archived"] is True
        assert "INBOX" not in result["result"]["labels"]


class TestMarkEmailRead:
    @pytest.mark.asyncio
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    async def test_mark_email_read_tool(self, mock_gmail, db_session: Session):
        _create_email(db_session, "msg_rd", labels=["INBOX", "UNREAD"], is_unread=True)
        mock_gmail.mark_as_read.return_value = {}

        result = _parse(await mark_email_read(message_id="msg_rd", _db=db_session))
        assert "result" in result
        assert result["result"]["is_unread"] is False


# ---------------------------------------------------------------------------
# Create tool
# ---------------------------------------------------------------------------


class TestDraftEmail:
    @pytest.mark.asyncio
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    async def test_draft_email_tool(self, mock_gmail, db_session: Session):
        mock_gmail.create_draft.return_value = {
            "id": "draft_1",
            "message": {"id": "msg_draft"},
        }

        result = _parse(await draft_email(
            to="recipient@example.com",
            subject="Hello",
            body="Hi there",
            _db=db_session,
        ))
        assert "result" in result
        assert result["result"]["draft_id"] == "draft_1"
        assert result["result"]["status"] == "draft_created"


# ---------------------------------------------------------------------------
# Execute tools
# ---------------------------------------------------------------------------


class TestSendEmail:
    @pytest.mark.asyncio
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    async def test_send_email_tool(self, mock_gmail, db_session: Session):
        mock_gmail.send_draft.return_value = {
            "id": "msg_sent",
            "threadId": "thread_sent",
        }

        result = _parse(await send_email(draft_id="draft_1", _db=db_session))
        assert "result" in result
        assert result["result"]["status"] == "sent"
        assert result["result"]["id"] == "msg_sent"


class TestSendReply:
    @pytest.mark.asyncio
    @patch("backend.openloop.services.email_integration_service.gmail_client")
    async def test_send_reply_tool(self, mock_gmail, db_session: Session):
        mock_gmail.send_reply.return_value = {
            "id": "msg_reply",
            "threadId": "thread_reply",
        }

        result = _parse(await send_reply(
            message_id="msg_original",
            body="Thanks!",
            _db=db_session,
        ))
        assert "result" in result
        assert result["result"]["status"] == "sent"


# ---------------------------------------------------------------------------
# Permission mapping
# ---------------------------------------------------------------------------


class TestPermissionMapping:
    def test_email_read_tools_permission(self):
        from backend.openloop.agents.permission_enforcer import _MCP_TOOL_MAP

        read_tools = ["list_emails", "get_email", "get_email_headers", "get_inbox_stats"]
        for tool_name in read_tools:
            assert tool_name in _MCP_TOOL_MAP, f"{tool_name} not in _MCP_TOOL_MAP"
            resource, operation = _MCP_TOOL_MAP[tool_name]
            assert resource == "gmail", f"{tool_name}: expected resource 'gmail', got '{resource}'"
            assert operation == "read", f"{tool_name}: expected operation 'read', got '{operation}'"

    def test_email_edit_tools_permission(self):
        from backend.openloop.agents.permission_enforcer import _MCP_TOOL_MAP

        edit_tools = ["label_email", "archive_email", "mark_email_read"]
        for tool_name in edit_tools:
            assert tool_name in _MCP_TOOL_MAP, f"{tool_name} not in _MCP_TOOL_MAP"
            resource, operation = _MCP_TOOL_MAP[tool_name]
            assert resource == "gmail", f"{tool_name}: expected resource 'gmail', got '{resource}'"
            assert operation == "edit", f"{tool_name}: expected operation 'edit', got '{operation}'"

    def test_email_create_tool_permission(self):
        from backend.openloop.agents.permission_enforcer import _MCP_TOOL_MAP

        assert "draft_email" in _MCP_TOOL_MAP
        resource, operation = _MCP_TOOL_MAP["draft_email"]
        assert resource == "gmail"
        assert operation == "create"

    def test_email_execute_tools_permission(self):
        from backend.openloop.agents.permission_enforcer import _MCP_TOOL_MAP

        execute_tools = ["send_email", "send_reply"]
        for tool_name in execute_tools:
            assert tool_name in _MCP_TOOL_MAP, f"{tool_name} not in _MCP_TOOL_MAP"
            resource, operation = _MCP_TOOL_MAP[tool_name]
            assert resource == "gmail", f"{tool_name}: expected resource 'gmail', got '{resource}'"
            assert operation == "execute", f"{tool_name}: expected operation 'execute', got '{operation}'"


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------


class TestEmailContextAssembly:
    def test_email_section_in_context(self, db_session: Session):
        """Create EmailCache records + gmail DataSource, verify email section appears."""
        from backend.openloop.agents.context_assembler import _build_email_section

        ds = _make_gmail_ds(db_session)
        _create_email(
            db_session, "msg_ctx",
            is_unread=True,
            labels=["INBOX", "UNREAD", "OL/Needs Response"],
            subject="Important Email",
            from_name="Boss",
        )

        result = _build_email_section(db_session, space_id=None)
        assert result != ""
        assert "Email" in result
        assert "Unread: 1" in result

    def test_email_section_empty_without_datasource(self, db_session: Session):
        """No Gmail DataSource -> returns empty string."""
        from backend.openloop.agents.context_assembler import _build_email_section

        result = _build_email_section(db_session, space_id=None)
        assert result == ""

    def test_email_section_excluded_for_space(self, db_session: Session):
        """DataSource excluded from a space -> empty result."""
        from backend.openloop.agents.context_assembler import _build_email_section

        ds = _make_gmail_ds(db_session)
        space = _make_space(db_session, "Excluded Space")
        _create_email(db_session, "msg_ex", is_unread=True)

        # Add exclusion
        db_session.execute(
            insert(space_data_source_exclusions).values(
                space_id=space.id,
                data_source_id=ds.id,
            )
        )
        db_session.commit()

        result = _build_email_section(db_session, space_id=space.id)
        assert result == ""
