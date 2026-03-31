from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import Document, Space


def _escape_like(s: str) -> str:
    """Escape special LIKE wildcard characters."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
    return query.order_by(Document.created_at.desc()).offset(offset).limit(limit).all()


def delete_document(db: Session, document_id: str) -> None:
    """Delete a document by ID, or 404."""
    doc = get_document(db, document_id)
    db.delete(doc)
    db.commit()
