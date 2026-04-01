"""Tests for document_service — Phase 4.3 additions (upload, scan, content, update, filtering)."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.services import document_service, space_service


def _make_space(db: Session, name: str = "Doc Space"):
    return space_service.create_space(db, name=name, template="project")


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_document(db_session: Session, tmp_path: Path):
    space = _make_space(db_session)
    with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
        doc = document_service.upload_document(
            db_session,
            space_id=space.id,
            filename="readme.md",
            file_content=b"# Hello World\nThis is a test.",
            content_type="text/markdown",
        )
    assert doc.title == "readme.md"
    assert doc.source == "upload"
    assert doc.file_size == len(b"# Hello World\nThis is a test.")
    assert doc.mime_type == "text/markdown"
    assert doc.content_text is not None
    assert "Hello World" in doc.content_text
    assert doc.indexed_at is not None
    assert doc.local_path is not None
    # File should exist on disk
    assert Path(doc.local_path).is_file()


def test_upload_document_binary(db_session: Session, tmp_path: Path):
    space = _make_space(db_session)
    with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
        doc = document_service.upload_document(
            db_session,
            space_id=space.id,
            filename="image.png",
            file_content=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
            content_type="image/png",
        )
    assert doc.title == "image.png"
    assert doc.content_text is None  # binary, no text extraction
    assert doc.file_size == 108


def test_upload_document_invalid_space(db_session: Session, tmp_path: Path):
    with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
        with pytest.raises(HTTPException) as exc_info:
            document_service.upload_document(
                db_session,
                space_id="nonexistent",
                filename="file.txt",
                file_content=b"data",
            )
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Scan directory
# ---------------------------------------------------------------------------


def test_scan_directory(db_session: Session, tmp_path: Path):
    space = _make_space(db_session)
    space_dir = tmp_path / space.id
    space_dir.mkdir()
    (space_dir / "notes.txt").write_text("some notes", encoding="utf-8")
    (space_dir / "data.csv").write_text("a,b\n1,2", encoding="utf-8")

    with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
        count = document_service.scan_directory(db_session, space.id)
    assert count == 2

    docs = document_service.list_documents(db_session, space_id=space.id)
    assert len(docs) == 2
    titles = {d.title for d in docs}
    assert "notes.txt" in titles
    assert "data.csv" in titles


def test_scan_directory_skips_already_indexed(db_session: Session, tmp_path: Path):
    space = _make_space(db_session)
    space_dir = tmp_path / space.id
    space_dir.mkdir()
    (space_dir / "existing.txt").write_text("already here", encoding="utf-8")

    with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
        count1 = document_service.scan_directory(db_session, space.id)
        count2 = document_service.scan_directory(db_session, space.id)
    assert count1 == 1
    assert count2 == 0  # no new files


def test_scan_directory_no_dir(db_session: Session, tmp_path: Path):
    space = _make_space(db_session)
    with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
        count = document_service.scan_directory(db_session, space.id)
    assert count == 0


def test_scan_directory_invalid_space(db_session: Session, tmp_path: Path):
    with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
        with pytest.raises(HTTPException) as exc_info:
            document_service.scan_directory(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Content retrieval
# ---------------------------------------------------------------------------


def test_get_document_content(db_session: Session, tmp_path: Path):
    space = _make_space(db_session)
    with patch.object(document_service, "DOCUMENTS_DIR", tmp_path):
        doc = document_service.upload_document(
            db_session,
            space_id=space.id,
            filename="test.txt",
            file_content=b"hello content",
        )
        file_path, mime = document_service.get_document_content(db_session, doc.id)
    assert file_path.is_file()
    assert file_path.read_text(encoding="utf-8") == "hello content"


def test_get_document_content_no_local_path(db_session: Session):
    space = _make_space(db_session)
    doc = document_service.create_document(db_session, space_id=space.id, title="Remote Only")
    with pytest.raises(HTTPException) as exc_info:
        document_service.get_document_content(db_session, doc.id)
    assert exc_info.value.status_code == 404


def test_get_document_content_missing_file(db_session: Session):
    space = _make_space(db_session)
    doc = document_service.create_document(
        db_session, space_id=space.id, title="Ghost", local_path="/nonexistent/path.txt"
    )
    with pytest.raises(HTTPException) as exc_info:
        document_service.get_document_content(db_session, doc.id)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def test_update_document_title(db_session: Session):
    space = _make_space(db_session)
    doc = document_service.create_document(db_session, space_id=space.id, title="Old Title")
    updated = document_service.update_document(db_session, doc.id, title="New Title")
    assert updated.title == "New Title"


def test_update_document_tags(db_session: Session):
    space = _make_space(db_session)
    doc = document_service.create_document(db_session, space_id=space.id, title="Tagged")
    updated = document_service.update_document(db_session, doc.id, tags=["new-tag", "other"])
    assert updated.tags == ["new-tag", "other"]


def test_update_document_not_found(db_session: Session):
    with pytest.raises(HTTPException) as exc_info:
        document_service.update_document(db_session, "nonexistent", title="X")
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# List with filters
# ---------------------------------------------------------------------------


def test_list_documents_filter_by_mime_type(db_session: Session):
    space = _make_space(db_session)
    document_service.create_document(
        db_session, space_id=space.id, title="A", mime_type="text/plain"
    )
    document_service.create_document(
        db_session, space_id=space.id, title="B", mime_type="image/png"
    )
    result = document_service.list_documents(db_session, mime_type="text/plain")
    assert len(result) == 1
    assert result[0].title == "A"


def test_list_documents_sort_by_title(db_session: Session):
    space = _make_space(db_session)
    document_service.create_document(db_session, space_id=space.id, title="Zebra")
    document_service.create_document(db_session, space_id=space.id, title="Apple")
    result = document_service.list_documents(db_session, sort_by="title")
    assert result[0].title == "Apple"
    assert result[1].title == "Zebra"


def test_list_documents_sort_by_size(db_session: Session):
    space = _make_space(db_session)
    document_service.create_document(
        db_session, space_id=space.id, title="Small", file_size=100
    )
    document_service.create_document(
        db_session, space_id=space.id, title="Big", file_size=10000
    )
    result = document_service.list_documents(db_session, sort_by="size")
    assert result[0].title == "Big"
    assert result[1].title == "Small"
