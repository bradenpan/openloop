import mimetypes
from datetime import UTC, datetime
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from backend.openloop.db.models import Document, Space

# Project root → data/documents/{space_id}/
_project_root = Path(__file__).resolve().parent.parent.parent.parent
DOCUMENTS_DIR = _project_root / "data" / "documents"

TEXT_EXTENSIONS = {
    ".txt", ".md", ".csv", ".json", ".py", ".js", ".ts", ".html", ".css",
    ".xml", ".yaml", ".yml", ".toml", ".cfg", ".ini", ".log", ".sql",
}


def _escape_like(s: str) -> str:
    """Escape special LIKE wildcard characters."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _is_text_file(filename: str) -> bool:
    """Check if a file has a text extension."""
    return Path(filename).suffix.lower() in TEXT_EXTENSIONS


def _extract_text(file_path: Path) -> str | None:
    """Extract text content from a file if it has a text extension."""
    if not _is_text_file(file_path.name):
        return None
    try:
        return file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _guess_mime_type(filename: str) -> str | None:
    """Guess MIME type from filename."""
    mime, _ = mimetypes.guess_type(filename)
    return mime


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_document(
    db: Session,
    *,
    space_id: str,
    title: str,
    source: str = "local",
    local_path: str | None = None,
    drive_file_id: str | None = None,
    drive_folder_id: str | None = None,
    tags: list[str] | None = None,
    file_size: int | None = None,
    mime_type: str | None = None,
    content_text: str | None = None,
) -> Document:
    """Index a document (local or Drive)."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    doc = Document(
        space_id=space_id,
        title=title,
        source=source,
        local_path=local_path,
        drive_file_id=drive_file_id,
        drive_folder_id=drive_folder_id,
        file_size=file_size,
        mime_type=mime_type,
        content_text=content_text,
        tags=tags,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def get_document(db: Session, document_id: str) -> Document:
    """Get a document by ID, or 404."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def list_documents(
    db: Session,
    *,
    space_id: str | None = None,
    search: str | None = None,
    tags: list[str] | None = None,
    mime_type: str | None = None,
    sort_by: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Document]:
    """List documents with optional filters."""
    query = db.query(Document)
    if space_id is not None:
        query = query.filter(Document.space_id == space_id)
    if search is not None:
        pattern = f"%{_escape_like(search)}%"
        query = query.filter(Document.title.ilike(pattern, escape="\\"))
    if mime_type is not None:
        query = query.filter(Document.mime_type == mime_type)
    if tags is not None:
        # Filter documents whose tags JSON array contains ALL specified tags.
        # SQLite JSON: use json_each to check containment.
        for tag in tags:
            query = query.filter(
                Document.tags.isnot(None),
                Document.title.is_not(None),  # keep query valid
            )
            # Use a simple approach: cast to string and check containment
            # For SQLite, we check if the JSON array contains the tag as a string element
            # func, literal_column, text imported at module level

            query = query.filter(
                text(f"EXISTS (SELECT 1 FROM json_each(documents.tags) WHERE json_each.value = :tag_{tag.replace('-', '_')})").bindparams(
                    **{f"tag_{tag.replace('-', '_')}": tag}
                )
            )

    # Sorting
    if sort_by == "title":
        query = query.order_by(Document.title.asc())
    elif sort_by == "size":
        query = query.order_by(func.coalesce(Document.file_size, 0).desc())
    elif sort_by == "updated":
        query = query.order_by(Document.updated_at.desc())
    else:
        query = query.order_by(Document.created_at.desc())

    return query.offset(offset).limit(limit).all()


_DOC_UPDATABLE_FIELDS = {"title", "tags"}


def update_document(db: Session, document_id: str, **kwargs: object) -> Document:
    """Update title/tags on a document."""
    doc = get_document(db, document_id)
    for key, value in kwargs.items():
        if key in _DOC_UPDATABLE_FIELDS:
            setattr(doc, key, value)
    db.commit()
    db.refresh(doc)
    return doc


def delete_document(db: Session, document_id: str) -> None:
    """Delete a document by ID, or 404."""
    doc = get_document(db, document_id)
    db.delete(doc)
    db.commit()


# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------


def upload_document(
    db: Session,
    *,
    space_id: str,
    filename: str,
    file_content: bytes,
    content_type: str | None = None,
) -> Document:
    """Save an uploaded file to data/documents/{space_id}/ and create a Document record."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    # Ensure target directory exists
    space_dir = DOCUMENTS_DIR / space_id
    space_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename to prevent path traversal
    filename = Path(filename).name
    if not filename or ".." in filename:
        raise HTTPException(status_code=422, detail="Invalid filename")

    # Write file
    file_path = space_dir / filename
    file_path.write_bytes(file_content)

    # Determine metadata
    file_size = len(file_content)
    mime = content_type or _guess_mime_type(filename)
    content_text = _extract_text(file_path) if _is_text_file(filename) else None

    doc = Document(
        space_id=space_id,
        title=filename,
        source="upload",
        local_path=str(file_path),
        file_size=file_size,
        mime_type=mime,
        content_text=content_text,
        indexed_at=datetime.now(UTC),
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# Directory scan
# ---------------------------------------------------------------------------


def scan_directory(db: Session, space_id: str) -> int:
    """Scan data/documents/{space_id}/, index any files not already tracked. Return count of new docs."""
    space = db.query(Space).filter(Space.id == space_id).first()
    if not space:
        raise HTTPException(status_code=404, detail="Space not found")

    space_dir = DOCUMENTS_DIR / space_id
    if not space_dir.is_dir():
        return 0

    # Get existing local_paths for this space
    existing_paths: set[str] = set()
    existing_docs = db.query(Document.local_path).filter(
        Document.space_id == space_id,
        Document.local_path.isnot(None),
    ).all()
    for (path,) in existing_docs:
        existing_paths.add(path)

    new_count = 0
    for entry in space_dir.iterdir():
        if not entry.is_file():
            continue
        entry_str = str(entry)
        if entry_str in existing_paths:
            continue

        file_size = entry.stat().st_size
        mime = _guess_mime_type(entry.name)
        content_text = _extract_text(entry)

        doc = Document(
            space_id=space_id,
            title=entry.name,
            source="scan",
            local_path=entry_str,
            file_size=file_size,
            mime_type=mime,
            content_text=content_text,
            indexed_at=datetime.now(UTC),
        )
        db.add(doc)
        new_count += 1

    if new_count > 0:
        db.commit()
    return new_count


# ---------------------------------------------------------------------------
# Content retrieval
# ---------------------------------------------------------------------------


def get_document_content(db: Session, document_id: str) -> tuple[Path, str | None]:
    """Return (file_path, mime_type) for streaming. Raises 404 if doc or file missing."""
    doc = get_document(db, document_id)
    if not doc.local_path:
        raise HTTPException(status_code=404, detail="Document has no local file")
    file_path = Path(doc.local_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return file_path, doc.mime_type
