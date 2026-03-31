from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import MemoryEntry


def _escape_like(s: str) -> str:
    """Escape special LIKE wildcard characters."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def create_entry(
    db: Session,
    *,
    namespace: str,
    key: str,
    value: str,
    tags: list[str] | None = None,
    source: str = "user",
) -> MemoryEntry:
    """Create a memory entry. Raises 409 if (namespace, key) already exists."""
    existing = (
        db.query(MemoryEntry)
        .filter(MemoryEntry.namespace == namespace, MemoryEntry.key == key)
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Memory entry '{namespace}:{key}' already exists. Use update instead.",
        )

    entry = MemoryEntry(
        namespace=namespace,
        key=key,
        value=value,
        tags=tags,
        source=source,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def get_entry(db: Session, entry_id: str) -> MemoryEntry:
    """Get a memory entry by ID, or 404."""
    entry = db.query(MemoryEntry).filter(MemoryEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Memory entry not found")
    return entry


def list_entries(
    db: Session,
    *,
    namespace: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[MemoryEntry]:
    """List memory entries with optional namespace filter and key/value search."""
    query = db.query(MemoryEntry)
    if namespace is not None:
        query = query.filter(MemoryEntry.namespace == namespace)
    if search is not None:
        pattern = f"%{_escape_like(search)}%"
        query = query.filter(
            (MemoryEntry.key.ilike(pattern, escape="\\"))
            | (MemoryEntry.value.ilike(pattern, escape="\\"))
        )
    return query.order_by(MemoryEntry.updated_at.desc()).offset(offset).limit(limit).all()


def update_entry(db: Session, entry_id: str, **kwargs) -> MemoryEntry:
    """Update a memory entry. Uses exclude_unset pattern."""
    entry = get_entry(db, entry_id)
    updatable = {"value", "tags", "source"}
    for field, value in kwargs.items():
        if field in updatable:
            setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    return entry


def upsert_entry(
    db: Session,
    *,
    namespace: str,
    key: str,
    value: str,
    tags: list[str] | None = None,
    source: str = "user",
) -> MemoryEntry:
    """Create or update a memory entry by (namespace, key)."""
    existing = (
        db.query(MemoryEntry)
        .filter(MemoryEntry.namespace == namespace, MemoryEntry.key == key)
        .first()
    )
    if existing:
        existing.value = value
        if tags is not None:
            existing.tags = tags
        existing.source = source
        db.commit()
        db.refresh(existing)
        return existing
    return create_entry(db, namespace=namespace, key=key, value=value, tags=tags, source=source)


def delete_entry(db: Session, entry_id: str) -> None:
    """Delete a memory entry by ID, or 404."""
    entry = get_entry(db, entry_id)
    db.delete(entry)
    db.commit()
