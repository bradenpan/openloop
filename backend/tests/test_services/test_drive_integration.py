"""Tests for Google Drive integration — gdrive_client, drive_integration_service, MCP tools.

All Google API calls are mocked. No real credentials needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from backend.openloop.db.models import DataSource, Document, Space


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_space(db: Session, name: str = "test-space") -> Space:
    space = Space(name=name, template="default")
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


MOCK_FILES = [
    {
        "id": "file-1",
        "name": "notes.txt",
        "mimeType": "text/plain",
        "size": "1234",
        "modifiedTime": "2026-03-30T12:00:00.000Z",
    },
    {
        "id": "file-2",
        "name": "report.csv",
        "mimeType": "text/csv",
        "size": "5678",
        "modifiedTime": "2026-03-30T13:00:00.000Z",
    },
    {
        "id": "file-3",
        "name": "image.png",
        "mimeType": "image/png",
        "size": "99999",
        "modifiedTime": "2026-03-30T14:00:00.000Z",
    },
]


# ---------------------------------------------------------------------------
# gdrive_client tests
# ---------------------------------------------------------------------------


class TestGdriveClient:
    @patch("backend.openloop.services.gdrive_client._TOKEN_PATH")
    def test_is_authenticated_no_token(self, mock_path):
        from backend.openloop.services import gdrive_client

        mock_path.exists.return_value = False
        assert gdrive_client.is_authenticated() is False

    @patch("backend.openloop.services.gdrive_client.get_drive_service")
    def test_list_files(self, mock_service):
        from backend.openloop.services import gdrive_client

        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.files.return_value.list.return_value.execute.return_value = {
            "files": MOCK_FILES
        }

        result = gdrive_client.list_files("folder-abc")
        assert len(result) == 3
        assert result[0]["name"] == "notes.txt"

    @patch("backend.openloop.services.gdrive_client.get_drive_service")
    def test_read_file_text_plain(self, mock_service):
        from backend.openloop.services import gdrive_client

        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.files.return_value.get.return_value.execute.return_value = {
            "mimeType": "text/plain",
            "name": "notes.txt",
        }
        mock_svc.files.return_value.get_media.return_value.execute.return_value = (
            b"hello world"
        )

        result = gdrive_client.read_file_text("file-1")
        assert result == "hello world"

    @patch("backend.openloop.services.gdrive_client.get_drive_service")
    def test_read_file_google_doc_exports(self, mock_service):
        from backend.openloop.services import gdrive_client

        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.files.return_value.get.return_value.execute.return_value = {
            "mimeType": "application/vnd.google-apps.document",
            "name": "My Doc",
        }
        mock_svc.files.return_value.export.return_value.execute.return_value = (
            b"exported text"
        )

        content, mime = gdrive_client.read_file("file-doc")
        assert content == b"exported text"
        assert mime == "text/plain"

    @patch("backend.openloop.services.gdrive_client.get_drive_service")
    def test_read_file_binary_returns_none_text(self, mock_service):
        from backend.openloop.services import gdrive_client

        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.files.return_value.get.return_value.execute.return_value = {
            "mimeType": "image/png",
            "name": "image.png",
        }
        mock_svc.files.return_value.get_media.return_value.execute.return_value = (
            b"\x89PNG\r\n"
        )

        result = gdrive_client.read_file_text("file-3")
        assert result is None

    @patch("backend.openloop.services.gdrive_client.get_drive_service")
    def test_create_file(self, mock_service):
        from backend.openloop.services import gdrive_client

        mock_svc = MagicMock()
        mock_service.return_value = mock_svc
        mock_svc.files.return_value.create.return_value.execute.return_value = {
            "id": "new-file-1",
            "name": "test.txt",
            "mimeType": "text/plain",
        }

        result = gdrive_client.create_file("folder-abc", "test.txt", "content here")
        assert result["id"] == "new-file-1"
        assert result["name"] == "test.txt"


# ---------------------------------------------------------------------------
# drive_integration_service tests
# ---------------------------------------------------------------------------


class TestDriveIntegrationService:
    @patch("backend.openloop.services.drive_integration_service.gdrive_client")
    def test_link_drive_folder_creates_data_source(self, mock_client, db_session):
        mock_client.list_files.return_value = []
        mock_client.read_file_text.return_value = None

        space = _make_space(db_session)

        from backend.openloop.services import drive_integration_service

        ds = drive_integration_service.link_drive_folder(
            db_session,
            space_id=space.id,
            folder_id="folder-xyz",
            folder_name="My Folder",
        )

        assert ds.source_type == "google_drive"
        assert ds.config["folder_id"] == "folder-xyz"
        assert ds.name == "My Folder"

    @patch("backend.openloop.services.drive_integration_service.gdrive_client")
    def test_link_duplicate_folder_409(self, mock_client, db_session):
        mock_client.list_files.return_value = []

        space = _make_space(db_session)

        from backend.openloop.services import drive_integration_service

        drive_integration_service.link_drive_folder(
            db_session,
            space_id=space.id,
            folder_id="folder-xyz",
            folder_name="My Folder",
        )

        with pytest.raises(Exception) as exc_info:
            drive_integration_service.link_drive_folder(
                db_session,
                space_id=space.id,
                folder_id="folder-xyz",
                folder_name="My Folder Again",
            )
        assert "409" in str(exc_info.value.status_code)

    @patch("backend.openloop.services.drive_integration_service.gdrive_client")
    def test_index_creates_documents(self, mock_client, db_session):
        mock_client.list_files.return_value = MOCK_FILES
        mock_client.read_file_text.side_effect = lambda fid: (
            "text content" if fid in ("file-1", "file-2") else None
        )

        space = _make_space(db_session)

        # Create data source manually
        ds = DataSource(
            space_id=space.id,
            source_type="google_drive",
            name="Test Folder",
            config={"folder_id": "folder-abc"},
        )
        db_session.add(ds)
        db_session.commit()
        db_session.refresh(ds)

        from backend.openloop.services import drive_integration_service

        count = drive_integration_service.index_drive_folder(
            db_session, data_source_id=ds.id
        )

        assert count == 3

        docs = (
            db_session.query(Document)
            .filter(Document.source == "drive", Document.space_id == space.id)
            .all()
        )
        assert len(docs) == 3
        titles = {d.title for d in docs}
        assert "notes.txt" in titles
        assert "report.csv" in titles
        assert "image.png" in titles

        # Check text content was set for text files
        text_doc = next(d for d in docs if d.title == "notes.txt")
        assert text_doc.content_text == "text content"

    @patch("backend.openloop.services.drive_integration_service.gdrive_client")
    def test_index_skips_existing(self, mock_client, db_session):
        mock_client.list_files.return_value = MOCK_FILES[:1]  # Just file-1
        mock_client.read_file_text.return_value = "content"

        space = _make_space(db_session)

        # Pre-existing document
        doc = Document(
            space_id=space.id,
            title="notes.txt",
            source="drive",
            drive_file_id="file-1",
            drive_folder_id="folder-abc",
        )
        db_session.add(doc)
        db_session.commit()

        ds = DataSource(
            space_id=space.id,
            source_type="google_drive",
            name="Test Folder",
            config={"folder_id": "folder-abc"},
        )
        db_session.add(ds)
        db_session.commit()
        db_session.refresh(ds)

        from backend.openloop.services import drive_integration_service

        count = drive_integration_service.index_drive_folder(
            db_session, data_source_id=ds.id
        )
        assert count == 0  # Already existed

    @patch("backend.openloop.services.drive_integration_service.gdrive_client")
    def test_refresh_adds_and_removes(self, mock_client, db_session):
        space = _make_space(db_session)

        # Existing document for file-1
        doc = Document(
            space_id=space.id,
            title="notes.txt",
            source="drive",
            drive_file_id="file-1",
            drive_folder_id="folder-abc",
        )
        db_session.add(doc)
        db_session.commit()

        ds = DataSource(
            space_id=space.id,
            source_type="google_drive",
            name="Test Folder",
            config={"folder_id": "folder-abc"},
        )
        db_session.add(ds)
        db_session.commit()
        db_session.refresh(ds)

        # Drive now has file-2 and file-3, but NOT file-1 (deleted)
        mock_client.list_files.return_value = MOCK_FILES[1:]
        mock_client.read_file_text.return_value = "new text"

        from backend.openloop.services import drive_integration_service

        result = drive_integration_service.refresh_drive_index(
            db_session, data_source_id=ds.id
        )

        assert result["added"] == 2
        assert result["removed"] == 1

        remaining = (
            db_session.query(Document)
            .filter(Document.source == "drive", Document.space_id == space.id)
            .all()
        )
        assert len(remaining) == 2
        remaining_ids = {d.drive_file_id for d in remaining}
        assert "file-1" not in remaining_ids
        assert "file-2" in remaining_ids
        assert "file-3" in remaining_ids


# ---------------------------------------------------------------------------
# MCP tool tests
# ---------------------------------------------------------------------------


class TestDriveMcpTools:
    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=True)
    @patch(
        "backend.openloop.services.gdrive_client.read_file_text",
        return_value="file content here",
    )
    async def test_read_drive_file(self, mock_read, mock_auth):
        import json

        from backend.openloop.agents.mcp_tools import read_drive_file

        result = json.loads(await read_drive_file("file-1"))
        assert "result" in result
        assert result["result"]["content"] == "file content here"

    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=False)
    async def test_read_drive_file_not_authenticated(self, mock_auth):
        import json

        from backend.openloop.agents.mcp_tools import read_drive_file

        result = json.loads(await read_drive_file("file-1"))
        assert result["is_error"] is True
        assert "not authenticated" in result["error"]

    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=True)
    @patch("backend.openloop.services.gdrive_client.list_files", return_value=MOCK_FILES)
    async def test_list_drive_files(self, mock_list, mock_auth):
        import json

        from backend.openloop.agents.mcp_tools import list_drive_files

        result = json.loads(await list_drive_files("folder-abc"))
        assert "result" in result
        assert len(result["result"]) == 3

    @pytest.mark.asyncio
    @patch("backend.openloop.services.gdrive_client.is_authenticated", return_value=True)
    @patch(
        "backend.openloop.services.gdrive_client.create_file",
        return_value={"id": "new-1", "name": "test.txt", "mimeType": "text/plain"},
    )
    async def test_create_drive_file(self, mock_create, mock_auth):
        import json

        from backend.openloop.agents.mcp_tools import create_drive_file

        result = json.loads(
            await create_drive_file("folder-abc", "test.txt", "hello")
        )
        assert "result" in result
        assert result["result"]["id"] == "new-1"
