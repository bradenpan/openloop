"""Service for memory entries — CRUD plus scored retrieval and write-time dedup.

Phase 3b additions: save_fact_with_dedup, get_scored_entries, archive_entry,
namespace caps, scoring formula, temporal fact management.
"""

import math
import re
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session

from backend.openloop.db.models import MemoryEntry
from contract.enums import DedupDecision

# ---------------------------------------------------------------------------
# Namespace caps
# ---------------------------------------------------------------------------

_NAMESPACE_CAPS: dict[str, int] = {
    "global": 50,
    "odin": 50,
}
# Patterns checked in _get_namespace_cap
_NAMESPACE_PATTERN_CAPS = [
    ("space:", 50),
    ("agent:", 20),
]


def _get_namespace_cap(namespace: str) -> int:
    """Return the max number of active entries allowed in a namespace."""
    if namespace in _NAMESPACE_CAPS:
        return _NAMESPACE_CAPS[namespace]
    for prefix, cap in _NAMESPACE_PATTERN_CAPS:
        if namespace.startswith(prefix):
            return cap
    # Default fallback for unknown namespaces
    return 50


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _compute_score(entry: MemoryEntry) -> float:
    """Compute retrieval score for a memory entry.

    Formula balances importance, recency decay, and access frequency.
    Higher importance slows decay. Frequent access provides a small boost.
    """
    reference = entry.last_accessed or entry.created_at
    # SQLite stores naive datetimes; strip tzinfo for safe subtraction
    now = datetime.now(UTC).replace(tzinfo=None)
    ref = reference.replace(tzinfo=None) if reference.tzinfo else reference
    days = max((now - ref).total_seconds() / 86400, 0)
    lambda_val = 0.16 * (1 - entry.importance * 0.8)
    return entry.importance * math.exp(-lambda_val * days) * (1 + entry.access_count * 0.2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _escape_like(s: str) -> str:
    """Escape special LIKE wildcard characters."""
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a URL-safe slug for use as a memory key.

    Appends a short UUID suffix to guarantee uniqueness within a namespace.
    """
    import uuid

    slug = text[:max_len].lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug)
    slug = slug.strip("-") or "fact"
    suffix = uuid.uuid4().hex[:6]
    return f"{slug}-{suffix}"


def _active_filter(query):
    """Apply filters for active (non-archived, temporally valid) entries."""
    return query.filter(
        MemoryEntry.archived_at.is_(None),
        MemoryEntry.valid_until.is_(None),
    )


# ---------------------------------------------------------------------------
# Original CRUD (backward compatible)
# ---------------------------------------------------------------------------


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
    include_archived: bool = False,
) -> list[MemoryEntry]:
    """List memory entries with optional namespace filter and key/value search.

    By default excludes archived and superseded entries.
    Set include_archived=True to see all.
    """
    query = db.query(MemoryEntry)
    if not include_archived:
        query = query.filter(
            MemoryEntry.archived_at.is_(None),
            MemoryEntry.valid_until.is_(None),
        )
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
    updatable = {"value", "tags", "source", "importance", "category"}
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


def supersede_entry(db: Session, entry_id: str) -> MemoryEntry:
    """Mark a memory entry as superseded by setting valid_until=now."""
    entry = get_entry(db, entry_id)
    entry.valid_until = datetime.now(UTC)
    db.commit()
    db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Phase 3b: Scored retrieval
# ---------------------------------------------------------------------------


def get_scored_entries(
    db: Session,
    namespace: str,
    *,
    limit: int | None = None,
    include_archived: bool = False,
    read_only: bool = False,
) -> list[MemoryEntry]:
    """Return entries ranked by score descending.

    Unless read_only=True, every retrieved entry gets access_count incremented
    and last_accessed set to now. Use read_only=True for estimation/dry-run paths
    to avoid inflating counters.
    """
    query = db.query(MemoryEntry).filter(MemoryEntry.namespace == namespace)
    if not include_archived:
        query = query.filter(
            MemoryEntry.archived_at.is_(None),
            MemoryEntry.valid_until.is_(None),
        )

    entries = query.all()

    # Sort by computed score descending
    entries.sort(key=_compute_score, reverse=True)

    if limit is not None:
        entries = entries[:limit]

    # Update access tracking on retrieved entries (skip in read_only mode)
    if not read_only:
        now = datetime.now(UTC)
        for entry in entries:
            entry.access_count += 1
            entry.last_accessed = now
        db.commit()

    return entries


# ---------------------------------------------------------------------------
# Phase 3b: Archive
# ---------------------------------------------------------------------------


def archive_entry(db: Session, entry_id: str) -> MemoryEntry:
    """Soft-archive a memory entry by setting archived_at."""
    entry = get_entry(db, entry_id)
    entry.archived_at = datetime.now(UTC)
    db.commit()
    db.refresh(entry)
    return entry


# ---------------------------------------------------------------------------
# Phase 3b: Write-time dedup
# ---------------------------------------------------------------------------


async def save_fact_with_dedup(
    db: Session,
    namespace: str,
    content: str,
    importance: float = 0.5,
    category: str | None = None,
    source: str = "agent",
) -> tuple[DedupDecision, MemoryEntry]:
    """Save a fact with LLM-powered deduplication.

    Loads all active facts in the namespace, asks the LLM to compare,
    then executes the appropriate action (ADD, UPDATE, DELETE/supersede, NOOP).

    Returns (decision, entry) where entry is the resulting MemoryEntry.
    """
    from backend.openloop.services.llm_utils import llm_compare_facts

    now = datetime.now(UTC)

    # Load active facts in namespace
    active_query = _active_filter(
        db.query(MemoryEntry).filter(MemoryEntry.namespace == namespace)
    )
    active_entries = active_query.all()

    # Prepare existing facts for LLM comparison
    existing_facts = [
        {"id": e.id, "key": e.key, "value": e.value} for e in active_entries
    ]

    # Ask LLM for dedup decision
    result = await llm_compare_facts(content, existing_facts)
    decision_str = result["decision"]
    target_id = result.get("target_id")
    merged_content = result.get("merged_content")

    decision = DedupDecision(decision_str)

    if decision == DedupDecision.NOOP:
        # Find the target entry if specified, otherwise return the first match
        if target_id:
            target = db.query(MemoryEntry).filter(MemoryEntry.id == target_id).first()
            if target:
                return (decision, target)
        # Fallback: return first active entry if any
        if active_entries:
            return (decision, active_entries[0])
        # Edge case: NOOP but no entries — treat as ADD
        decision = DedupDecision.ADD

    if decision == DedupDecision.UPDATE:
        if target_id:
            target = db.query(MemoryEntry).filter(MemoryEntry.id == target_id).first()
            if target:
                target.value = merged_content or content
                target.updated_at = now
                db.commit()
                db.refresh(target)
                return (decision, target)
        # Fallback if target not found — treat as ADD
        decision = DedupDecision.ADD

    if decision == DedupDecision.DELETE:
        # Supersession: expire old fact, create new one
        if target_id:
            old_entry = db.query(MemoryEntry).filter(MemoryEntry.id == target_id).first()
            if old_entry:
                old_entry.valid_until = now
                db.flush()

        # Enforce namespace cap before adding (the old entry is now expired, not counted)
        _enforce_namespace_cap(db, namespace, active_entries, exclude_id=target_id)

        new_entry = MemoryEntry(
            namespace=namespace,
            key=_slugify(content),
            value=content,
            importance=importance,
            category=category,
            source=source,
            valid_from=now,
        )
        db.add(new_entry)
        db.commit()
        db.refresh(new_entry)
        return (decision, new_entry)

    # decision == DedupDecision.ADD
    _enforce_namespace_cap(db, namespace, active_entries)

    new_entry = MemoryEntry(
        namespace=namespace,
        key=_slugify(content),
        value=content,
        importance=importance,
        category=category,
        source=source,
        valid_from=now,
    )
    db.add(new_entry)
    db.commit()
    db.refresh(new_entry)
    return (DedupDecision.ADD, new_entry)


def _enforce_namespace_cap(
    db: Session,
    namespace: str,
    active_entries: list[MemoryEntry],
    exclude_id: str | None = None,
) -> None:
    """If namespace is at capacity, archive the lowest-scored entry.

    Args:
        exclude_id: An entry ID to exclude from the active count (e.g., one being superseded).
    """
    cap = _get_namespace_cap(namespace)

    # Count currently active entries, excluding any being superseded
    counted = [e for e in active_entries if e.id != exclude_id] if exclude_id else active_entries

    if len(counted) >= cap:
        # Find lowest-scored entry to archive
        lowest = min(counted, key=_compute_score)
        lowest.archived_at = datetime.now(UTC)
        db.flush()
