"""Full-text search service using SQLite FTS5.

All functions receive a SQLAlchemy Session and use raw SQL (text()) since
FTS5 is SQLite-specific and has no ORM representation.
"""

from __future__ import annotations

import html
import re

from sqlalchemy import text
from sqlalchemy.orm import Session

# Unique delimiters for FTS5 snippet — replaced with <mark> after HTML escaping
_SNIPPET_OPEN = "\x00MARK_OPEN\x00"
_SNIPPET_CLOSE = "\x00MARK_CLOSE\x00"


def _safe_snippet(raw_excerpt: str) -> str:
    """HTML-escape a FTS5 snippet, then restore <mark> tags for highlighting."""
    escaped = html.escape(raw_excerpt)
    escaped = escaped.replace(html.escape(_SNIPPET_OPEN), "<mark>")
    escaped = escaped.replace(html.escape(_SNIPPET_CLOSE), "</mark>")
    return escaped


# ---------------------------------------------------------------------------
# Query sanitization
# ---------------------------------------------------------------------------

# FTS5 special characters that need escaping / stripping
_FTS5_SPECIAL = re.compile(r'["\(\)\*\:\^\{\}\[\]~\|&!]')


def _sanitize_query(raw: str) -> str:
    """Sanitize user input for FTS5 MATCH.

    Strips FTS5 operators, collapses whitespace, wraps each token with
    double-quotes to prevent syntax errors, then joins with spaces
    (implicit AND).
    """
    cleaned = _FTS5_SPECIAL.sub(" ", raw)
    tokens = cleaned.split()
    if not tokens:
        return ""
    # Quote each individual token so FTS5 treats them as literals
    return " ".join(f'"{t}"' for t in tokens)


# ---------------------------------------------------------------------------
# Individual search helpers
# ---------------------------------------------------------------------------


def search_messages(
    db: Session,
    query: str,
    *,
    space_id: str | None = None,
    space_ids: list[str] | None = None,
    conversation_id: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search conversation messages via FTS5.

    space_id filters to a single space. space_ids filters to a list of
    allowed spaces (for permission scoping). If both are provided,
    space_id takes precedence.
    """
    safe_q = _sanitize_query(query)
    if not safe_q:
        return []

    sql = """
        SELECT
            cm.id,
            cm.conversation_id,
            cm.role,
            cm.created_at,
            snippet(fts_conversation_messages, 0, :snip_open, :snip_close, '...', 48) AS excerpt,
            bm25(fts_conversation_messages) AS rank,
            c.name AS conversation_name,
            c.space_id,
            s.name AS space_name
        FROM fts_conversation_messages fts
        JOIN conversation_messages cm ON cm.rowid = fts.rowid
        JOIN conversations c ON c.id = cm.conversation_id
        LEFT JOIN spaces s ON s.id = c.space_id
        WHERE fts_conversation_messages MATCH :query
    """
    params: dict = {"query": safe_q, "limit": limit, "snip_open": _SNIPPET_OPEN, "snip_close": _SNIPPET_CLOSE}

    if space_id:
        sql += " AND c.space_id = :space_id"
        params["space_id"] = space_id
    elif space_ids is not None:
        placeholders = ", ".join(f":sid_{i}" for i in range(len(space_ids)))
        sql += f" AND c.space_id IN ({placeholders})"
        for i, sid in enumerate(space_ids):
            params[f"sid_{i}"] = sid
    if conversation_id:
        sql += " AND cm.conversation_id = :conversation_id"
        params["conversation_id"] = conversation_id

    sql += " ORDER BY rank LIMIT :limit"

    rows = db.execute(text(sql), params).fetchall()
    return [
        {
            "id": r.id,
            "type": "message",
            "title": f"{r.role} in {r.conversation_name}",
            "excerpt": _safe_snippet(r.excerpt or ""),
            "space_id": r.space_id,
            "space_name": r.space_name,
            "relevance_score": abs(r.rank),
            "created_at": r.created_at,
            "source_id": r.conversation_id,
        }
        for r in rows
    ]


def search_summaries(
    db: Session,
    query: str,
    *,
    space_id: str | None = None,
    space_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search conversation summaries via FTS5.

    space_id filters to a single space. space_ids filters to a list of
    allowed spaces (for permission scoping). If both are provided,
    space_id takes precedence.
    """
    safe_q = _sanitize_query(query)
    if not safe_q:
        return []

    sql = """
        SELECT
            cs.id,
            cs.conversation_id,
            cs.space_id,
            cs.created_at,
            snippet(fts_conversation_summaries, 0, :snip_open, :snip_close, '...', 48) AS excerpt,
            bm25(fts_conversation_summaries) AS rank,
            c.name AS conversation_name,
            s.name AS space_name
        FROM fts_conversation_summaries fts
        JOIN conversation_summaries cs ON cs.rowid = fts.rowid
        JOIN conversations c ON c.id = cs.conversation_id
        LEFT JOIN spaces s ON s.id = cs.space_id
        WHERE fts_conversation_summaries MATCH :query
    """
    params: dict = {"query": safe_q, "limit": limit, "snip_open": _SNIPPET_OPEN, "snip_close": _SNIPPET_CLOSE}

    if space_id:
        sql += " AND cs.space_id = :space_id"
        params["space_id"] = space_id
    elif space_ids is not None:
        placeholders = ", ".join(f":sid_{i}" for i in range(len(space_ids)))
        sql += f" AND cs.space_id IN ({placeholders})"
        for i, sid in enumerate(space_ids):
            params[f"sid_{i}"] = sid

    sql += " ORDER BY rank LIMIT :limit"

    rows = db.execute(text(sql), params).fetchall()
    return [
        {
            "id": r.id,
            "type": "summary",
            "title": f"Summary: {r.conversation_name}",
            "excerpt": _safe_snippet(r.excerpt or ""),
            "space_id": r.space_id,
            "space_name": r.space_name,
            "relevance_score": abs(r.rank),
            "created_at": r.created_at,
            "source_id": r.conversation_id,
        }
        for r in rows
    ]


def search_memory(
    db: Session,
    query: str,
    *,
    namespace: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search active memory entries via FTS5."""
    safe_q = _sanitize_query(query)
    if not safe_q:
        return []

    sql = """
        SELECT
            me.id,
            me.namespace,
            me.key,
            me.created_at,
            snippet(fts_memory_entries, 0, :snip_open, :snip_close, '...', 48) AS excerpt,
            bm25(fts_memory_entries) AS rank
        FROM fts_memory_entries fts
        JOIN memory_entries me ON me.rowid = fts.rowid
        WHERE fts_memory_entries MATCH :query
    """
    params: dict = {"query": safe_q, "limit": limit, "snip_open": _SNIPPET_OPEN, "snip_close": _SNIPPET_CLOSE}

    if namespace:
        sql += " AND me.namespace = :namespace"
        params["namespace"] = namespace

    sql += " ORDER BY rank LIMIT :limit"

    rows = db.execute(text(sql), params).fetchall()
    return [
        {
            "id": r.id,
            "type": "memory",
            "title": f"{r.namespace}/{r.key}",
            "excerpt": _safe_snippet(r.excerpt or ""),
            "space_id": None,
            "space_name": None,
            "relevance_score": abs(r.rank),
            "created_at": r.created_at,
            "source_id": r.id,
        }
        for r in rows
    ]


def search_documents(
    db: Session,
    query: str,
    *,
    space_id: str | None = None,
    space_ids: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search documents via FTS5 (title only for now).

    space_id filters to a single space. space_ids filters to a list of
    allowed spaces (for permission scoping). If both are provided,
    space_id takes precedence.
    """
    safe_q = _sanitize_query(query)
    if not safe_q:
        return []

    sql = """
        SELECT
            d.id,
            d.title,
            d.space_id,
            d.source,
            d.created_at,
            snippet(fts_documents, -1, :snip_open, :snip_close, '...', 48) AS excerpt,
            bm25(fts_documents) AS rank,
            s.name AS space_name
        FROM fts_documents fts
        JOIN documents d ON d.rowid = fts.rowid
        LEFT JOIN spaces s ON s.id = d.space_id
        WHERE fts_documents MATCH :query
    """
    params: dict = {"query": safe_q, "limit": limit, "snip_open": _SNIPPET_OPEN, "snip_close": _SNIPPET_CLOSE}

    if space_id:
        sql += " AND d.space_id = :space_id"
        params["space_id"] = space_id
    elif space_ids is not None:
        placeholders = ", ".join(f":sid_{i}" for i in range(len(space_ids)))
        sql += f" AND d.space_id IN ({placeholders})"
        for i, sid in enumerate(space_ids):
            params[f"sid_{i}"] = sid

    sql += " ORDER BY rank LIMIT :limit"

    rows = db.execute(text(sql), params).fetchall()
    return [
        {
            "id": r.id,
            "type": "document",
            "title": r.title,
            "excerpt": _safe_snippet(r.excerpt or ""),
            "space_id": r.space_id,
            "space_name": r.space_name,
            "relevance_score": abs(r.rank),
            "created_at": r.created_at,
            "source_id": r.id,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Unified search
# ---------------------------------------------------------------------------


def search_all(
    db: Session,
    query: str,
    *,
    space_id: str | None = None,
    limit: int = 50,
) -> dict[str, list[dict]]:
    """Search all FTS tables and group results by type."""
    per_type = max(limit // 4, 5)

    return {
        "messages": search_messages(db, query, space_id=space_id, limit=per_type),
        "summaries": search_summaries(db, query, space_id=space_id, limit=per_type),
        "memory": search_memory(db, query, limit=per_type),
        "documents": search_documents(db, query, space_id=space_id, limit=per_type),
    }


# ---------------------------------------------------------------------------
# Index maintenance
# ---------------------------------------------------------------------------


def rebuild_fts_indexes(db: Session) -> None:
    """Rebuild all FTS5 indexes from source table data.

    Uses the FTS5 'rebuild' command which re-reads all content from
    the external content tables.
    """
    for table in [
        "fts_conversation_messages",
        "fts_conversation_summaries",
        "fts_memory_entries",
        "fts_documents",
    ]:
        db.execute(text(f"INSERT INTO {table}({table}) VALUES('rebuild');"))
    db.commit()


# ---------------------------------------------------------------------------
# Startup check
# ---------------------------------------------------------------------------


def check_and_rebuild_if_needed(db: Session) -> bool:
    """Check if FTS tables exist and are populated; rebuild if stale.

    Returns True if a rebuild was performed, False otherwise.
    """
    fts_tables = [
        ("fts_conversation_messages", "conversation_messages"),
        ("fts_conversation_summaries", "conversation_summaries"),
        ("fts_memory_entries", "memory_entries"),
        ("fts_documents", "documents"),
    ]

    for fts_table, source_table in fts_tables:
        # Check if FTS table exists
        result = db.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=:name"
            ),
            {"name": fts_table},
        ).fetchone()
        if not result:
            # FTS tables don't exist yet (migration not run)
            return False

    # FTS tables exist — check if any source has data but FTS is empty
    for fts_table, source_table in fts_tables:
        source_count = db.execute(
            text(f"SELECT COUNT(*) FROM {source_table}")  # noqa: S608
        ).scalar()
        if source_count and source_count > 0:
            fts_count = db.execute(
                text(f"SELECT COUNT(*) FROM {fts_table}")  # noqa: S608
            ).scalar()
            if not fts_count or fts_count == 0:
                rebuild_fts_indexes(db)
                return True

    return False
