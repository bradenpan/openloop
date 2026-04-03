"""MCP tool definitions for OpenLoop agents.

Each tool is an async function decorated with @tool(). Tools create their own
short-lived DB sessions via SessionLocal() (or an injected `_db` for testing).

All inputs arrive as strings from the SDK regardless of type annotation —
always coerce before use. All tools return JSON strings.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.openloop.database import SessionLocal
from backend.openloop.services import (
    agent_service,
    background_task_service,
    behavioral_rule_service,
    conversation_service,
    document_service,
    item_link_service,
    item_service,
    layout_service,
    memory_service,
    search_service,
    space_service,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db(_db=None):
    """Return the provided test session or create a new production session."""
    return _db if _db is not None else SessionLocal()


def _parse_bool(value: str) -> bool | None:
    """Parse a string to bool. Empty string -> None."""
    if not value:
        return None
    return value.lower() in ("true", "1", "yes")


def _parse_int(value: str, default: int | None = None) -> int | None:
    """Parse a string to int. Empty string -> default."""
    if not value:
        return default
    return int(value)


def _parse_date(value: str) -> datetime | None:
    """Parse an ISO date string. Empty string -> None."""
    if not value:
        return None
    return datetime.fromisoformat(value)


def _ok(result) -> str:
    return json.dumps({"result": result})


def _err(msg: str) -> str:
    return json.dumps({"is_error": True, "error": msg})


def _get_agent_space_ids(db: Session, agent_id: str) -> list[str] | None:
    """Get space IDs this agent has access to via the agent_spaces join table.

    Returns None for system agents (like Odin) that have no space restrictions,
    meaning they can search all spaces. Returns a list of space IDs for scoped agents.
    """
    if not agent_id:
        return None
    rows = db.execute(
        text("SELECT space_id FROM agent_spaces WHERE agent_id = :agent_id"),
        {"agent_id": agent_id},
    ).fetchall()
    if not rows:
        # No space restrictions — system agent (Odin) or agent with global access
        return None
    return [r[0] for r in rows]


def _validate_space_access(db: Session, agent_id: str, space_id: str) -> str | None:
    """Check that agent_id has access to space_id.

    Returns None if access is allowed, or an error JSON string if denied.
    System agents (no space restrictions) are always allowed.
    """
    allowed = _get_agent_space_ids(db, agent_id)
    if allowed is None:
        # System agent — no restrictions
        return None
    if space_id in allowed:
        return None
    return _err(f"Agent does not have access to space {space_id}")


# ---------------------------------------------------------------------------
# Standard tools (1–28): available to all agents
# ---------------------------------------------------------------------------


# 1. create_task
async def create_task(
    space_id: str, title: str, due_date: str = "",
    *, _db=None, _agent_name: str = "agent", _agent_id: str = "",
) -> str:
    """Create a task in a space. due_date is optional ISO format (e.g. 2025-01-15)."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        item = item_service.create_item(
            db,
            space_id=space_id,
            title=title,
            item_type="task",
            due_date=_parse_date(due_date),
            created_by=_agent_name,
        )
        return _ok(
            {
                "id": item.id,
                "title": item.title,
                "space_id": item.space_id,
                "is_done": item.is_done,
                "due_date": item.due_date.isoformat() if item.due_date else None,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 2. complete_task
async def complete_task(
    item_id: str, *, _db=None, _agent_id: str = "",
) -> str:
    """Mark a task as done."""
    db = _get_db(_db)
    try:
        existing = item_service.get_item(db, item_id)
        denied = _validate_space_access(
            db, _agent_id, existing.space_id
        )
        if denied:
            return denied
        item = item_service.update_item(db, item_id, is_done=True)
        return _ok({"id": item.id, "title": item.title, "is_done": True})
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 3. list_tasks
async def list_tasks(
    space_id: str = "", is_done: str = "",
    *, _db=None, _agent_id: str = "",
) -> str:
    """List tasks. Empty string = no filter. is_done: 'true'/'false'/''."""
    db = _get_db(_db)
    try:
        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied
        items = item_service.list_items(
            db,
            space_id=space_id or None,
            item_type="task",
            is_done=_parse_bool(is_done),
        )
        # Post-filter to agent's allowed spaces when no space_id
        if not space_id:
            allowed = _get_agent_space_ids(db, _agent_id)
            if allowed is not None:
                items = [i for i in items if i.space_id in allowed]
        return _ok(
            [
                {
                    "id": t.id,
                    "title": t.title,
                    "is_done": t.is_done,
                    "space_id": t.space_id,
                    "stage": t.stage,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                }
                for t in items
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 4. create_item
async def create_item(
    space_id: str,
    title: str,
    item_type: str = "task",
    stage: str = "",
    description: str = "",
    is_done: str = "false",
    *,
    _db=None,
    _agent_name: str = "agent",
    _agent_id: str = "",
) -> str:
    """Create a board item (task or record) in a space."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        item = item_service.create_item(
            db,
            space_id=space_id,
            title=title,
            item_type=item_type or "task",
            stage=stage or None,
            description=description or None,
            is_done=_parse_bool(is_done) or False,
            created_by=_agent_name,
        )
        return _ok(
            {
                "id": item.id,
                "title": item.title,
                "item_type": item.item_type,
                "stage": item.stage,
                "space_id": item.space_id,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 5. update_item
async def update_item(
    item_id: str,
    title: str = "",
    description: str = "",
    priority: str = "",
    *,
    _db=None,
    _agent_name: str = "agent",
    _agent_id: str = "",
) -> str:
    """Update board item fields. Empty string = don't change."""
    db = _get_db(_db)
    try:
        existing = item_service.get_item(db, item_id)
        denied = _validate_space_access(
            db, _agent_id, existing.space_id
        )
        if denied:
            return denied
        kwargs = {}
        if title:
            kwargs["title"] = title
        if description:
            kwargs["description"] = description
        if priority:
            kwargs["priority"] = _parse_int(priority)
        item = item_service.update_item(db, item_id, triggered_by=_agent_name, **kwargs)
        return _ok(
            {
                "id": item.id,
                "title": item.title,
                "description": item.description,
                "priority": item.priority,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 6. move_item
async def move_item(
    item_id: str, stage: str,
    *, _db=None, _agent_name: str = "agent",
    _agent_id: str = "",
) -> str:
    """Move a board item to a different stage."""
    db = _get_db(_db)
    try:
        existing = item_service.get_item(db, item_id)
        denied = _validate_space_access(
            db, _agent_id, existing.space_id
        )
        if denied:
            return denied
        item = item_service.move_item(db, item_id, stage, triggered_by=_agent_name)
        return _ok({"id": item.id, "title": item.title, "stage": item.stage})
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 7. get_item
async def get_item(
    item_id: str, *, _db=None, _agent_id: str = "",
) -> str:
    """Get full details of a board item."""
    db = _get_db(_db)
    try:
        item = item_service.get_item(db, item_id)
        denied = _validate_space_access(
            db, _agent_id, item.space_id
        )
        if denied:
            return denied
        return _ok(
            {
                "id": item.id,
                "title": item.title,
                "item_type": item.item_type,
                "stage": item.stage,
                "description": item.description,
                "priority": item.priority,
                "space_id": item.space_id,
                "created_by": item.created_by,
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 8. list_items
async def list_items(
    space_id: str = "", stage: str = "", item_type: str = "",
    is_done: str = "", limit: str = "20",
    *, _db=None, _agent_id: str = "",
) -> str:
    """List board items with optional filters. is_done: 'true'/'false'/'' (empty = no filter)."""
    db = _get_db(_db)
    try:
        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied
        limit_int = _parse_int(limit, 20)
        items = item_service.list_items(
            db,
            space_id=space_id or None,
            stage=stage or None,
            item_type=item_type or None,
            is_done=_parse_bool(is_done),
        )
        # Post-filter to agent's allowed spaces when no space_id
        if not space_id:
            allowed = _get_agent_space_ids(db, _agent_id)
            if allowed is not None:
                items = [i for i in items if i.space_id in allowed]
        # Apply limit
        items = items[:limit_int]
        return _ok(
            [
                {
                    "id": i.id,
                    "title": i.title,
                    "item_type": i.item_type,
                    "stage": i.stage,
                }
                for i in items
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 9. read_memory
async def read_memory(namespace: str = "", key: str = "", search: str = "", *, _db=None) -> str:
    """Read memory entries. Filter by namespace, key, or search term."""
    db = _get_db(_db)
    try:
        entries = memory_service.list_entries(
            db,
            namespace=namespace or None,
            search=search or key or None,
        )
        return _ok(
            [
                {
                    "id": e.id,
                    "namespace": e.namespace,
                    "key": e.key,
                    "value": e.value,
                    "tags": e.tags,
                }
                for e in entries
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 10. write_memory
async def write_memory(
    namespace: str, key: str, value: str, tags: str = "", *, _db=None, _agent_name: str = "agent"
) -> str:
    """Write or upsert a memory entry. tags is comma-separated."""
    db = _get_db(_db)
    try:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        entry = memory_service.upsert_entry(
            db,
            namespace=namespace,
            key=key,
            value=value,
            tags=tag_list,
            source=_agent_name,
        )
        return _ok(
            {
                "id": entry.id,
                "namespace": entry.namespace,
                "key": entry.key,
                "value": entry.value,
                "tags": entry.tags,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# ---------------------------------------------------------------------------
# Phase 3b: Enhanced memory + behavioral rule tools
# ---------------------------------------------------------------------------


# save_fact (smart write with dedup)
async def save_fact(
    content: str,
    namespace: str = "",
    importance: str = "0.5",
    category: str = "",
    *,
    _db=None,
    _agent_name: str = "agent",
) -> str:
    """Save a fact to memory with automatic deduplication.

    The system checks if this fact is new, updates existing, or supersedes old facts.
    namespace defaults to 'agent:<agent_name>' if not provided.
    importance is a float 0.0-1.0 (default 0.5).
    """
    db = _get_db(_db)
    try:
        ns = namespace or f"agent:{_agent_name}"
        imp = float(importance) if importance else 0.5
        cat = category or None
        decision, entry = await memory_service.save_fact_with_dedup(
            db,
            namespace=ns,
            content=content,
            importance=imp,
            category=cat,
            source=_agent_name,
        )
        return _ok(
            {
                "decision": decision.value,
                "id": entry.id,
                "namespace": entry.namespace,
                "key": entry.key,
                "value": entry.value,
                "importance": entry.importance,
                "category": entry.category,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# update_fact
async def update_fact(fact_id: str, new_content: str, *, _db=None) -> str:
    """Explicitly update an existing fact's content by ID."""
    db = _get_db(_db)
    try:
        entry = memory_service.update_entry(db, fact_id, value=new_content)
        return _ok(
            {
                "id": entry.id,
                "namespace": entry.namespace,
                "key": entry.key,
                "value": entry.value,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# recall_facts (smart read with scoring — FTS5 backed)
async def recall_facts(
    query: str = "", namespace: str = "", category: str = "", limit: str = "20", *, _db=None
) -> str:
    """Search and retrieve facts from memory using full-text search.

    query: search terms for FTS5 search across memory values.
    namespace: filter by namespace. If provided without query, returns
        scored entries from that namespace (importance-based ranking).
    category: filter by category.
    limit: max results for FTS5 search (default 20).

    When query is provided, uses FTS5 BM25 ranking. When only namespace
    is provided, falls back to importance-based scored retrieval.
    """
    db = _get_db(_db)
    try:
        limit_int = _parse_int(limit, 20)

        if query and query.strip():
            # FTS5 search with BM25 ranking
            fts_results = search_service.search_memory(
                db,
                query,
                namespace=namespace or None,
                limit=limit_int,
            )
            if category:
                # Post-filter by category (FTS5 doesn't index category)
                # We need to look up the actual entry for category filtering
                filtered = []
                for r in fts_results:
                    from backend.openloop.db.models import MemoryEntry

                    entry = db.query(MemoryEntry).filter(MemoryEntry.id == r["id"]).first()
                    if entry and (not category or entry.category == category):
                        r["importance"] = entry.importance
                        r["category"] = entry.category
                        r["tags"] = entry.tags
                        r["access_count"] = entry.access_count
                        filtered.append(r)
                fts_results = filtered
            else:
                # Enrich results with importance/category/tags from the ORM
                from backend.openloop.db.models import MemoryEntry

                for r in fts_results:
                    entry = db.query(MemoryEntry).filter(MemoryEntry.id == r["id"]).first()
                    if entry:
                        r["importance"] = entry.importance
                        r["category"] = entry.category
                        r["tags"] = entry.tags
                        r["access_count"] = entry.access_count

            return _ok(
                [
                    {
                        "id": r["id"],
                        "namespace": r["title"].split("/")[0] if "/" in r["title"] else "",
                        "key": r["title"].split("/")[1] if "/" in r["title"] else r["title"],
                        "value": r["excerpt"],
                        "importance": r.get("importance", 0.5),
                        "category": r.get("category"),
                        "tags": r.get("tags"),
                        "relevance_score": r["relevance_score"],
                        "access_count": r.get("access_count", 0),
                    }
                    for r in fts_results
                ]
            )
        elif namespace:
            # Namespace-based scored retrieval (importance ranking)
            entries = memory_service.get_scored_entries(db, namespace, read_only=True)
            if category:
                entries = [e for e in entries if e.category == category]
            return _ok(
                [
                    {
                        "id": e.id,
                        "namespace": e.namespace,
                        "key": e.key,
                        "value": e.value,
                        "importance": e.importance,
                        "category": e.category,
                        "tags": e.tags,
                    }
                    for e in entries
                ]
            )
        else:
            # No query and no namespace — return all entries
            entries = memory_service.list_entries(db)
            if category:
                entries = [e for e in entries if e.category == category]
            return _ok(
                [
                    {
                        "id": e.id,
                        "namespace": e.namespace,
                        "key": e.key,
                        "value": e.value,
                        "importance": e.importance,
                        "category": e.category,
                        "tags": e.tags,
                    }
                    for e in entries
                ]
            )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# delete_fact
async def delete_fact(fact_id: str, reason: str = "", *, _db=None) -> str:
    """Mark a fact as superseded (sets valid_until=now). Provide a reason."""
    db = _get_db(_db)
    try:
        entry = memory_service.supersede_entry(db, fact_id)
        return _ok(
            {
                "id": entry.id,
                "value": entry.value,
                "valid_until": entry.valid_until.isoformat(),
                "reason": reason,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# save_rule
async def save_rule(
    rule: str,
    source_type: str = "correction",
    source_context: str = "",
    *,
    _db=None,
    _agent_name: str = "agent",
    _agent_id: str = "",
) -> str:
    """Save a behavioral rule learned from user correction or validation.

    source_type: 'correction' or 'validation'.
    source_context: optional conversation ID or other context.
    """
    db = _get_db(_db)
    try:
        entry = behavioral_rule_service.create_rule(
            db,
            agent_id=_agent_id,
            rule=rule,
            source_type=source_type or "correction",
            source_conversation_id=source_context or None,
        )
        return _ok(
            {
                "id": entry.id,
                "agent_id": entry.agent_id,
                "rule": entry.rule,
                "confidence": entry.confidence,
                "source_type": entry.source_type,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# confirm_rule
async def confirm_rule(rule_id: str, *, _db=None) -> str:
    """Confirm a rule was correct — increases confidence by 0.1 (capped at 1.0)."""
    db = _get_db(_db)
    try:
        entry = behavioral_rule_service.confirm_rule(db, rule_id)
        return _ok(
            {
                "id": entry.id,
                "rule": entry.rule,
                "confidence": entry.confidence,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# override_rule
async def override_rule(rule_id: str, *, _db=None) -> str:
    """User contradicted this rule — decreases confidence by 0.2.

    If confidence drops below 0.3 and rule has been applied 10+ times,
    the rule is automatically deactivated.
    """
    db = _get_db(_db)
    try:
        entry = behavioral_rule_service.override_rule(db, rule_id)
        return _ok(
            {
                "id": entry.id,
                "rule": entry.rule,
                "confidence": entry.confidence,
                "is_active": entry.is_active,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# list_rules
async def list_rules(
    agent_id: str = "", *, _db=None, _agent_name: str = "agent", _agent_id: str = ""
) -> str:
    """List active behavioral rules for an agent.

    agent_id defaults to the current agent if not provided.
    """
    db = _get_db(_db)
    try:
        aid = agent_id or _agent_id
        rules = behavioral_rule_service.list_rules(db, agent_id=aid)
        return _ok(
            [
                {
                    "id": r.id,
                    "rule": r.rule,
                    "confidence": r.confidence,
                    "source_type": r.source_type,
                    "apply_count": r.apply_count,
                    "is_active": r.is_active,
                }
                for r in rules
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 11. read_document
async def read_document(
    document_id: str, *, _db=None, _agent_id: str = "",
) -> str:
    """Get document metadata by ID."""
    db = _get_db(_db)
    try:
        doc = document_service.get_document(db, document_id)
        denied = _validate_space_access(
            db, _agent_id, doc.space_id
        )
        if denied:
            return denied
        return _ok(
            {
                "id": doc.id,
                "title": doc.title,
                "source": doc.source,
                "space_id": doc.space_id,
                "tags": doc.tags,
                "indexed_at": doc.indexed_at.isoformat() if doc.indexed_at else None,
                "created_at": doc.created_at.isoformat(),
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 12. list_documents
async def list_documents(
    space_id: str = "", search: str = "",
    *, _db=None, _agent_id: str = "",
) -> str:
    """List documents with optional space filter and title search."""
    db = _get_db(_db)
    try:
        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied
        docs = document_service.list_documents(
            db,
            space_id=space_id or None,
            search=search or None,
        )
        # Post-filter to agent's allowed spaces when no space_id
        if not space_id:
            allowed = _get_agent_space_ids(db, _agent_id)
            if allowed is not None:
                docs = [d for d in docs if d.space_id in allowed]
        return _ok(
            [
                {
                    "id": d.id,
                    "title": d.title,
                    "source": d.source,
                    "space_id": d.space_id,
                    "tags": d.tags,
                }
                for d in docs
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 13. create_document
async def create_document(
    space_id: str, title: str, source: str = "local",
    tags: str = "", *, _db=None, _agent_id: str = "",
) -> str:
    """Index a document in a space. tags is comma-separated."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        doc = document_service.create_document(
            db,
            space_id=space_id,
            title=title,
            source=source or "local",
            tags=tag_list,
        )
        return _ok(
            {
                "id": doc.id,
                "title": doc.title,
                "source": doc.source,
                "space_id": doc.space_id,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 14. get_board_state
async def get_board_state(space_id: str, *, _db=None, _agent_id: str = "") -> str:
    """Get a summary of all board items grouped by stage."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        space = space_service.get_space(db, space_id)
        # Intentionally high limit to capture the full board state for context assembly
        items = item_service.list_items(db, space_id=space_id, limit=10000)
        grouped: dict[str, list] = {}
        for item in items:
            stage = item.stage or "unassigned"
            grouped.setdefault(stage, []).append(
                {
                    "id": item.id,
                    "title": item.title,
                    "item_type": item.item_type,
                    "priority": item.priority,
                }
            )
        return _ok(
            {
                "space_id": space.id,
                "space_name": space.name,
                "columns": space.board_columns,
                "stages": grouped,
                "total_items": len(items),
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 15. get_task_state
async def get_task_state(space_id: str = "", *, _db=None, _agent_id: str = "") -> str:
    """Get summary of tasks: counts by status, overdue items."""
    db = _get_db(_db)
    try:
        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied
        all_tasks = item_service.list_items(
            db, space_id=space_id or None, item_type="task", archived=False, limit=200
        )
        done = [t for t in all_tasks if t.is_done]
        pending = [t for t in all_tasks if not t.is_done]
        now = datetime.now(UTC)
        overdue = [
            {
                "id": t.id,
                "title": t.title,
                "due_date": t.due_date.isoformat(),
                "space_id": t.space_id,
            }
            for t in pending
            if t.due_date and t.due_date < now
        ]
        return _ok(
            {
                "total": len(all_tasks),
                "done": len(done),
                "pending": len(pending),
                "overdue_count": len(overdue),
                "overdue_items": overdue,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 16. get_conversation_summaries
async def get_conversation_summaries(
    space_id: str, limit: str = "5",
    *, _db=None, _agent_id: str = "",
) -> str:
    """Get recent conversation summaries for a space."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        limit_int = _parse_int(limit, 5)
        summaries = conversation_service.get_summaries(db, space_id=space_id)
        summaries = summaries[:limit_int]
        return _ok(
            [
                {
                    "id": s.id,
                    "conversation_id": s.conversation_id,
                    "summary": s.summary,
                    "decisions": s.decisions,
                    "open_questions": s.open_questions,
                    "created_at": s.created_at.isoformat(),
                }
                for s in summaries
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 17. search_conversations
async def search_conversations(
    query: str,
    space_id: str = "",
    conversation_id: str = "",
    limit: str = "20",
    *,
    _db=None,
    _agent_id: str = "",
) -> str:
    """Search conversation messages using full-text search (FTS5).

    query: the search terms (required).
    space_id: filter to a specific space. If omitted, searches across all
        spaces this agent has access to.
    conversation_id: filter to a specific conversation.
    limit: max results (default 20).
    """
    db = _get_db(_db)
    try:
        if not query or not query.strip():
            return _ok([])

        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied

        limit_int = _parse_int(limit, 20)
        sid = space_id or None
        cid = conversation_id or None

        # Determine space scoping for cross-space search
        space_ids = None
        if not sid:
            space_ids = _get_agent_space_ids(db, _agent_id)
            # space_ids=None means system agent — search everything

        results = search_service.search_messages(
            db,
            query,
            space_id=sid,
            space_ids=space_ids,
            conversation_id=cid,
            limit=limit_int,
        )
        return _ok(
            [
                {
                    "message_id": r["id"],
                    "conversation_id": r["source_id"],
                    "role": r["title"].split(" in ")[0] if " in " in r["title"] else "",
                    "excerpt": r["excerpt"],
                    "space_id": r["space_id"],
                    "space_name": r["space_name"],
                    "relevance_score": r["relevance_score"],
                    "created_at": r["created_at"],
                }
                for r in results
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 17b. search_summaries
async def search_summaries(
    query: str,
    space_id: str = "",
    limit: str = "20",
    *,
    _db=None,
    _agent_id: str = "",
) -> str:
    """Search conversation summaries using full-text search (FTS5).

    query: the search terms (required).
    space_id: filter to a specific space. If omitted, searches across all
        spaces this agent has access to.
    limit: max results (default 20).
    """
    db = _get_db(_db)
    try:
        if not query or not query.strip():
            return _ok([])

        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied

        limit_int = _parse_int(limit, 20)
        sid = space_id or None

        # Determine space scoping for cross-space search
        space_ids = None
        if not sid:
            space_ids = _get_agent_space_ids(db, _agent_id)

        results = search_service.search_summaries(
            db,
            query,
            space_id=sid,
            space_ids=space_ids,
            limit=limit_int,
        )
        return _ok(
            [
                {
                    "summary_id": r["id"],
                    "conversation_id": r["source_id"],
                    "conversation_name": r["title"].removeprefix("Summary: "),
                    "excerpt": r["excerpt"],
                    "space_id": r["space_id"],
                    "space_name": r["space_name"],
                    "relevance_score": r["relevance_score"],
                    "created_at": r["created_at"],
                }
                for r in results
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 18. get_conversation_messages
async def get_conversation_messages(conversation_id: str, limit: str = "20", *, _db=None) -> str:
    """Get recent messages from a conversation."""
    db = _get_db(_db)
    try:
        limit_int = _parse_int(limit, 20)
        messages = conversation_service.get_messages(db, conversation_id)
        # Return the most recent N messages
        messages = messages[-limit_int:] if len(messages) > limit_int else messages
        return _ok(
            [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 19. delegate_task
async def delegate_task(
    agent_name: str, instruction: str,
    space_id: str = "", parent_task_id: str = "",
    *, _db=None, _agent_id: str = "",
) -> str:
    """Delegate a task to another agent to run in the background.

    Args:
        agent_name: Name of the agent to delegate to.
        instruction: What the agent should do.
        space_id: Optional space context for the delegated work.
        parent_task_id: Optional parent task ID for hierarchical tracking.
    Returns:
        JSON with the background task ID.
    """
    from backend.openloop.agents import agent_runner

    db = _get_db(_db)
    try:
        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied
        agent = agent_service.get_agent_by_name(db, agent_name)
        task_id = await agent_runner.delegate_background(
            db,
            agent_id=agent.id,
            instruction=instruction,
            space_id=space_id or None,
            parent_task_id=parent_task_id or None,
        )
        return _ok({"task_id": task_id, "agent": agent_name, "status": "running"})
    except HTTPException as exc:
        return _err(exc.detail)
    except (Exception, ExceptionGroup) as exc:
        return _err(f"Delegation failed: {exc}")
    finally:
        if _db is None:
            db.close()


# 19b. update_task_progress
async def update_task_progress(
    task_id: str, step: str, total_steps: str, summary: str, *, _db=None
) -> str:
    """Report progress on a background task.

    Args:
        task_id: The background task ID to update.
        step: Current step number (1-based).
        total_steps: Total number of steps.
        summary: Brief description of what this step accomplished.
    """
    db = _get_db(_db)
    try:
        background_task_service.update_task_progress(
            db,
            task_id=task_id,
            current_step=int(step),
            total_steps=int(total_steps),
            step_summary=summary,
        )
        return _ok({"task_id": task_id, "step": int(step), "total_steps": int(total_steps)})
    except HTTPException as exc:
        return _err(exc.detail)
    except ValueError:
        return _err("step and total_steps must be integers")
    finally:
        if _db is None:
            db.close()


# ---------------------------------------------------------------------------
# Agent Builder-only tools
# ---------------------------------------------------------------------------


async def register_agent(
    skill_name: str, model: str = "sonnet", space_names: str = "", description: str = "", *, _db=None
) -> str:
    """Register a skill-based agent in OpenLoop.

    Creates or updates an agent DB record pointing to agents/skills/{skill_name}/SKILL.md.

    Args:
        skill_name: Directory name under agents/skills/ (e.g. 'recruiting')
        model: Default model (haiku, sonnet, opus). Defaults to sonnet.
        space_names: Comma-separated space names to link the agent to.
        description: Agent description. If empty, extracted from SKILL.md frontmatter.
    """
    import os
    import re

    db = _get_db(_db)
    try:
        # Validate skill_name to prevent path traversal
        if ".." in skill_name or "/" in skill_name or "\\" in skill_name:
            return _err("Invalid skill name — must not contain path separators")

        skill_path = f"agents/skills/{skill_name}"
        # Verify SKILL.md exists
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        skill_md = os.path.join(project_root, skill_path, "SKILL.md")

        # Verify resolved path stays under project root
        real_path = os.path.realpath(skill_md)
        if not real_path.startswith(os.path.realpath(project_root)):
            return _err("Invalid skill path")

        if not os.path.exists(skill_md):
            return _err(f"SKILL.md not found at {skill_path}/SKILL.md")

        # Parse frontmatter for name and description
        with open(skill_md, encoding="utf-8") as f:
            content = f.read()

        fm_name = skill_name
        fm_desc = description
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                frontmatter = content[3:end]
                name_match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
                if name_match:
                    fm_name = name_match.group(1).strip()
                if not fm_desc:
                    desc_match = re.search(r"^description:\s*\|?\s*\n([\s\S]*?)(?=\n\w|\Z)", frontmatter, re.MULTILINE)
                    if desc_match:
                        fm_desc = desc_match.group(1).strip()[:500]

        # Check if agent already exists
        existing = db.query(agent_service.Agent).filter(agent_service.Agent.name == fm_name).first()
        if existing:
            agent = agent_service.update_agent(
                db, existing.id, skill_path=skill_path, default_model=model,
                description=fm_desc or existing.description,
            )
        else:
            agent = agent_service.create_agent(
                db, name=fm_name, description=fm_desc, skill_path=skill_path, default_model=model,
            )

        # Link to spaces
        if space_names:
            for sname in space_names.split(","):
                sname = sname.strip()
                if sname:
                    space = db.query(space_service.Space).filter(space_service.Space.name == sname).first()
                    if space and space not in agent.spaces:
                        agent.spaces.append(space)
            db.commit()

        return _ok({"agent_id": agent.id, "name": fm_name, "skill_path": skill_path, "status": "registered"})
    except HTTPException as exc:
        return _err(exc.detail)
    finally:
        if _db is None:
            db.close()


async def test_agent(
    skill_name: str, test_prompt: str, space_id: str = "",
    *, _db=None, _agent_id: str = "",
) -> str:
    """Test a draft agent by running a test conversation via delegation.

    Args:
        skill_name: The skill directory name under agents/skills/.
        test_prompt: The test scenario to run against the draft agent.
        space_id: Optional space context for the test.
    """
    from backend.openloop.agents import agent_runner

    db = _get_db(_db)
    try:
        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied

        # Find or create a temporary agent for testing
        agent_name = skill_name
        existing = db.query(agent_service.Agent).filter(
            agent_service.Agent.name == agent_name
        ).first()
        caller_space_ids = _get_agent_space_ids(db, _agent_id)
        if not existing:
            # Register it first — link to the calling agent's spaces so the
            # test agent cannot access data outside the builder's scope.
            skill_path = f"agents/skills/{skill_name}"
            existing = agent_service.create_agent(
                db, name=agent_name,
                description=f"Test agent for {skill_name}",
                skill_path=skill_path,
                space_ids=caller_space_ids,
            )
        else:
            # Update space linkage to match caller's current scope
            existing.spaces.clear()
            if caller_space_ids:
                for sid in caller_space_ids:
                    sp = db.query(space_service.Space).filter(
                        space_service.Space.id == sid
                    ).first()
                    if sp:
                        existing.spaces.append(sp)
            db.commit()

        task_id = await agent_runner.delegate_background(
            db,
            agent_id=existing.id,
            instruction=test_prompt,
            space_id=space_id or None,
        )
        return _ok({"task_id": task_id, "agent": agent_name, "status": "test_running"})
    except HTTPException as exc:
        return _err(exc.detail)
    except (Exception, ExceptionGroup) as exc:
        return _err(f"Test failed to start: {exc}")
    finally:
        if _db is None:
            db.close()


# ---------------------------------------------------------------------------
# Odin-only tools (20–25)
# ---------------------------------------------------------------------------


# 20. list_spaces
async def list_spaces(*, _db=None) -> str:
    """List all spaces with basic info."""
    db = _get_db(_db)
    try:
        spaces = space_service.list_spaces(db)
        return _ok(
            [
                {
                    "id": s.id,
                    "name": s.name,
                    "template": s.template,
                    "description": s.description,
                    "board_enabled": s.board_enabled,
                    "created_at": s.created_at.isoformat(),
                }
                for s in spaces
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 21. list_agents
async def list_agents(space_id: str = "", *, _db=None) -> str:
    """List agents, optionally filtered by space membership."""
    db = _get_db(_db)
    try:
        agents = agent_service.list_agents(db)
        if space_id:
            agents = [a for a in agents if any(s.id == space_id for s in a.spaces)]
        return _ok(
            [
                {
                    "id": a.id,
                    "name": a.name,
                    "description": a.description,
                    "status": a.status,
                    "default_model": a.default_model,
                }
                for a in agents
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 22. open_conversation
async def open_conversation(
    space_id: str, agent_id: str,
    initial_message: str = "", model: str = "",
    *, _db=None, _agent_id: str = "",
) -> str:
    """Create a new conversation. Returns routing info for the frontend."""
    db = _get_db(_db)
    try:
        if space_id:
            denied = _validate_space_access(db, _agent_id, space_id)
            if denied:
                return denied
        conv = conversation_service.create_conversation(
            db,
            space_id=space_id or None,
            agent_id=agent_id,
            name=initial_message[:50] if initial_message else "New conversation",
            model_override=model or None,
        )
        return _ok(
            {
                "conversation_id": conv.id,
                "space_id": conv.space_id,
                "agent_id": conv.agent_id,
                "initial_message": initial_message,
                "route": f"/spaces/{conv.space_id}/conversations/{conv.id}",
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 23. navigate_to_space
async def navigate_to_space(space_id: str, *, _db=None, _agent_id: str = "") -> str:
    """Returns a navigation instruction for the frontend."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        space = space_service.get_space(db, space_id)
        return _ok(
            {
                "action": "navigate",
                "route": f"/spaces/{space.id}",
                "space_name": space.name,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 24. get_attention_items
async def get_attention_items(*, _db=None) -> str:
    """Get pending approvals, overdue to-dos, and items due today."""
    from backend.openloop.db.models import PermissionRequest

    db = _get_db(_db)
    try:
        # Pending permission requests
        pending = db.query(PermissionRequest).filter(PermissionRequest.status == "pending").all()
        pending_approvals = [
            {
                "id": p.id,
                "agent_id": p.agent_id,
                "tool_name": p.tool_name,
                "resource": p.resource,
                "created_at": p.created_at.isoformat(),
            }
            for p in pending
        ]

        # Overdue tasks
        now = datetime.now(UTC)
        all_tasks = item_service.list_items(db, item_type="task", is_done=False, archived=False, limit=200)
        overdue = [
            {
                "id": t.id,
                "title": t.title,
                "space_id": t.space_id,
                "due_date": t.due_date.isoformat(),
            }
            for t in all_tasks
            if t.due_date and t.due_date < now
        ]

        # Due today
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
        due_today = [
            {
                "id": t.id,
                "title": t.title,
                "space_id": t.space_id,
                "due_date": t.due_date.isoformat(),
            }
            for t in all_tasks
            if t.due_date and today_start <= t.due_date <= today_end
        ]

        return _ok(
            {
                "pending_approvals": pending_approvals,
                "overdue_tasks": overdue,
                "due_today": due_today,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 25. get_cross_space_tasks
async def get_cross_space_tasks(is_done: str = "", *, _db=None) -> str:
    """Get tasks across all spaces."""
    db = _get_db(_db)
    try:
        items = item_service.list_items(db, item_type="task", is_done=_parse_bool(is_done))
        return _ok(
            [
                {
                    "id": t.id,
                    "title": t.title,
                    "is_done": t.is_done,
                    "space_id": t.space_id,
                    "stage": t.stage,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                }
                for t in items
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# ---------------------------------------------------------------------------
# Google Drive tools (26-28)
# ---------------------------------------------------------------------------


# 26. read_drive_file
async def read_drive_file(file_id: str, *, _db=None) -> str:
    """Read text content of a Google Drive file by its file ID."""
    try:
        from backend.openloop.services import gdrive_client

        if not gdrive_client.is_authenticated():
            return _err("Google Drive is not authenticated. Link a Drive folder first.")

        text = gdrive_client.read_file_text(file_id)
        if text is None:
            return _err("File is binary or could not be read as text")
        # Truncate very large files to avoid overwhelming context
        if len(text) > 50000:
            text = text[:50000] + "\n\n... [truncated at 50,000 characters]"
        return _ok({"file_id": file_id, "content": text})
    except Exception as e:
        return _err(str(e))


# 27. list_drive_files
async def list_drive_files(folder_id: str, *, _db=None) -> str:
    """List files in a Google Drive folder."""
    try:
        from backend.openloop.services import gdrive_client

        if not gdrive_client.is_authenticated():
            return _err("Google Drive is not authenticated. Link a Drive folder first.")

        files = gdrive_client.list_files(folder_id)
        return _ok(
            [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "mimeType": f.get("mimeType"),
                    "size": f.get("size"),
                    "modifiedTime": f.get("modifiedTime"),
                }
                for f in files
            ]
        )
    except Exception as e:
        return _err(str(e))


# 28. create_drive_file
async def create_drive_file(
    folder_id: str, name: str, content: str, mime_type: str = "text/plain", *, _db=None
) -> str:
    """Create a new file in a Google Drive folder."""
    try:
        from backend.openloop.services import gdrive_client

        if not gdrive_client.is_authenticated():
            return _err("Google Drive is not authenticated. Link a Drive folder first.")

        result = gdrive_client.create_file(folder_id, name, content, mime_type)
        return _ok({"id": result["id"], "name": result["name"], "mimeType": result.get("mimeType")})
    except Exception as e:
        return _err(str(e))


# ---------------------------------------------------------------------------
# Layout tools (29-33): available to all agents
# ---------------------------------------------------------------------------


# 29. get_space_layout
async def get_space_layout(
    space_id: str, *, _db=None, _agent_id: str = "",
) -> str:
    """Get the widget layout for a space. Returns an ordered list of widgets with their types, sizes, positions, and configurations."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        widgets = layout_service.get_layout(db, space_id)
        return _ok(
            [
                {
                    "id": w.id,
                    "widget_type": w.widget_type,
                    "position": w.position,
                    "size": w.size,
                    "config": w.config,
                }
                for w in widgets
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 30. add_widget
async def add_widget(
    space_id: str,
    widget_type: str,
    position: str = "",
    size: str = "medium",
    config: str = "",
    *,
    _db=None,
    _agent_id: str = "",
) -> str:
    """Add a widget to a space's layout. widget_type must be one of: todo_panel, kanban_board, data_table, conversations, chart, stat_card, markdown, data_feed. size is one of: small, medium, large, full. position is 0-indexed (omit to append at end). config is optional JSON string for widget-specific settings."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        position_int = _parse_int(position)
        config_dict = json.loads(config) if config else None
        widget = layout_service.add_widget(
            db,
            space_id,
            widget_type=widget_type,
            position=position_int,
            size=size,
            config=config_dict,
        )
        return _ok(
            {
                "id": widget.id,
                "widget_type": widget.widget_type,
                "position": widget.position,
                "size": widget.size,
                "config": widget.config,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 31. update_widget
async def update_widget(
    widget_id: str,
    size: str = "",
    config: str = "",
    position: str = "",
    *,
    _db=None,
    _agent_id: str = "",
) -> str:
    """Update a widget's size, config, or position. Only provided fields are changed. config is a JSON string."""
    db = _get_db(_db)
    try:
        kwargs = {}
        if size:
            kwargs["size"] = size
        if config:
            kwargs["config"] = json.loads(config)
        if position:
            kwargs["position"] = _parse_int(position)
        # Look up the widget's space for ownership validation
        from backend.openloop.db.models import SpaceWidget as _SW

        _w = db.query(_SW.space_id).filter(_SW.id == widget_id).first()
        if not _w:
            return _err("Widget not found")
        denied = _validate_space_access(
            db, _agent_id, _w.space_id
        )
        if denied:
            return denied
        widget = layout_service.update_widget(db, _w.space_id, widget_id, **kwargs)
        return _ok(
            {
                "id": widget.id,
                "widget_type": widget.widget_type,
                "position": widget.position,
                "size": widget.size,
                "config": widget.config,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 32. remove_widget
async def remove_widget(
    widget_id: str, *, _db=None, _agent_id: str = "",
) -> str:
    """Remove a widget from a space's layout. Remaining widgets are automatically reordered."""
    db = _get_db(_db)
    try:
        # Look up the widget's space for ownership validation
        from backend.openloop.db.models import SpaceWidget as _SW

        _w = db.query(_SW.space_id).filter(_SW.id == widget_id).first()
        if not _w:
            return _err("Widget not found")
        denied = _validate_space_access(
            db, _agent_id, _w.space_id
        )
        if denied:
            return denied
        layout_service.remove_widget(db, _w.space_id, widget_id)
        return _ok({"removed": widget_id})
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 33. set_space_layout
async def set_space_layout(space_id: str, widgets: str, *, _db=None, _agent_id: str = "") -> str:
    """Bulk replace a space's entire layout. widgets is a JSON array of objects with widget_type (required), size (optional, default 'medium'), and config (optional). Positions are assigned automatically. Use this for full layout redesigns."""
    db = _get_db(_db)
    try:
        denied = _validate_space_access(db, _agent_id, space_id)
        if denied:
            return denied
        widgets_list = json.loads(widgets)
        new_widgets = layout_service.set_layout(db, space_id, widgets_list)
        return _ok(
            [
                {
                    "id": w.id,
                    "widget_type": w.widget_type,
                    "position": w.position,
                    "size": w.size,
                    "config": w.config,
                }
                for w in new_widgets
            ]
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# ---------------------------------------------------------------------------
# Item link tools (34-36)
# ---------------------------------------------------------------------------


# 34. link_items
async def link_items(
    source_item_id: str, target_item_id: str,
    link_type: str = "related_to",
    *, _db=None, _agent_id: str = "",
) -> str:
    """Create an association between two items."""
    db = _get_db(_db)
    try:
        src = item_service.get_item(db, source_item_id)
        denied = _validate_space_access(
            db, _agent_id, src.space_id
        )
        if denied:
            return denied
        tgt = item_service.get_item(db, target_item_id)
        denied = _validate_space_access(
            db, _agent_id, tgt.space_id
        )
        if denied:
            return denied
        link = item_link_service.create_link(
            db,
            source_item_id=source_item_id,
            target_item_id=target_item_id,
            link_type=link_type or "related_to",
        )
        return _ok(
            {
                "id": link.id,
                "source_item_id": link.source_item_id,
                "target_item_id": link.target_item_id,
                "link_type": link.link_type,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 35. unlink_items
async def unlink_items(
    link_id: str, *, _db=None, _agent_id: str = "",
) -> str:
    """Remove an association between items by link ID."""
    db = _get_db(_db)
    try:
        from backend.openloop.db.models import ItemLink as _IL

        lnk = db.query(_IL).filter(_IL.id == link_id).first()
        if not lnk:
            return _err("Link not found")
        src = item_service.get_item(db, lnk.source_item_id)
        denied = _validate_space_access(
            db, _agent_id, src.space_id
        )
        if denied:
            return denied
        item_link_service.delete_link(db, link_id)
        return _ok({"deleted": link_id})
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 36. get_linked_items
async def get_linked_items(
    item_id: str, link_type: str = "",
    *, _db=None, _agent_id: str = "",
) -> str:
    """Get all items linked to this item (bidirectional)."""
    db = _get_db(_db)
    try:
        existing = item_service.get_item(db, item_id)
        denied = _validate_space_access(
            db, _agent_id, existing.space_id
        )
        if denied:
            return denied
        links = item_link_service.list_links_for_item(
            db, item_id, link_type=link_type or None
        )
        result = []
        for link in links:
            # Resolve the "other" item in the link
            other_id = link.target_item_id if link.source_item_id == item_id else link.source_item_id
            other = item_service.get_item(db, other_id)
            result.append(
                {
                    "link_id": link.id,
                    "link_type": link.link_type,
                    "item_id": other.id,
                    "title": other.title,
                    "item_type": other.item_type,
                    "stage": other.stage,
                    "is_done": other.is_done,
                }
            )
        return _ok(result)
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 37. archive_item
async def archive_item(
    item_id: str,
    *, _db=None, _agent_name: str = "agent",
    _agent_id: str = "",
) -> str:
    """Archive an item (hidden from active views, still searchable)."""
    db = _get_db(_db)
    try:
        existing = item_service.get_item(db, item_id)
        denied = _validate_space_access(
            db, _agent_id, existing.space_id
        )
        if denied:
            return denied
        item = item_service.archive_item(db, item_id, triggered_by=_agent_name)
        return _ok({"id": item.id, "title": item.title, "archived": True})
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# ---------------------------------------------------------------------------
# Builder functions
# ---------------------------------------------------------------------------

# Tool registry: maps tool name -> function
_STANDARD_TOOLS = {
    "create_task": create_task,
    "complete_task": complete_task,
    "list_tasks": list_tasks,
    "create_item": create_item,
    "update_item": update_item,
    "move_item": move_item,
    "get_item": get_item,
    "list_items": list_items,
    "read_memory": read_memory,
    "write_memory": write_memory,
    "save_fact": save_fact,
    "update_fact": update_fact,
    "recall_facts": recall_facts,
    "delete_fact": delete_fact,
    "save_rule": save_rule,
    "confirm_rule": confirm_rule,
    "override_rule": override_rule,
    "list_rules": list_rules,
    "read_document": read_document,
    "list_documents": list_documents,
    "create_document": create_document,
    "get_board_state": get_board_state,
    "get_task_state": get_task_state,
    "get_conversation_summaries": get_conversation_summaries,
    "search_conversations": search_conversations,
    "search_summaries": search_summaries,
    "get_conversation_messages": get_conversation_messages,
    "delegate_task": delegate_task,
    "update_task_progress": update_task_progress,
    "read_drive_file": read_drive_file,
    "list_drive_files": list_drive_files,
    "create_drive_file": create_drive_file,
    "get_space_layout": get_space_layout,
    "add_widget": add_widget,
    "update_widget": update_widget,
    "remove_widget": remove_widget,
    "set_space_layout": set_space_layout,
    "link_items": link_items,
    "unlink_items": unlink_items,
    "get_linked_items": get_linked_items,
    "archive_item": archive_item,
}

_ODIN_TOOLS = {
    "list_spaces": list_spaces,
    "list_agents": list_agents,
    "open_conversation": open_conversation,
    "navigate_to_space": navigate_to_space,
    "get_attention_items": get_attention_items,
    "get_cross_space_tasks": get_cross_space_tasks,
}


def _make_decorated_tools(tool_map: dict, agent_name: str, agent_id: str = "") -> list:
    """Wrap raw async functions with @tool() and inject _agent_name/_agent_id via closures."""
    from claude_agent_sdk import tool

    decorated = []
    for name, fn in tool_map.items():
        # Build a closure that binds agent_name/agent_id for tools that support them
        import inspect

        sig = inspect.signature(fn)
        has_agent_name = "_agent_name" in sig.parameters
        has_agent_id = "_agent_id" in sig.parameters

        if has_agent_name or has_agent_id:
            # Create closure binding agent_name and/or agent_id
            def _make_wrapper(original_fn, bound_name, bound_id, inject_name, inject_id):
                async def wrapper(**kwargs):
                    if inject_name:
                        kwargs["_agent_name"] = bound_name
                    if inject_id:
                        kwargs["_agent_id"] = bound_id
                    return await original_fn(**kwargs)

                # Copy metadata for the SDK
                wrapper.__name__ = original_fn.__name__
                wrapper.__doc__ = original_fn.__doc__
                # Copy annotations, excluding internal params
                wrapper.__annotations__ = {
                    k: v
                    for k, v in original_fn.__annotations__.items()
                    if not k.startswith("_") and k != "return"
                }
                wrapper.__annotations__["return"] = str
                return wrapper

            wrapped = _make_wrapper(fn, agent_name, agent_id, has_agent_name, has_agent_id)
        else:
            # No agent_name needed, but still strip internal params from annotations
            def _make_clean_wrapper(original_fn):
                async def wrapper(**kwargs):
                    return await original_fn(**kwargs)

                wrapper.__name__ = original_fn.__name__
                wrapper.__doc__ = original_fn.__doc__
                wrapper.__annotations__ = {
                    k: v
                    for k, v in original_fn.__annotations__.items()
                    if not k.startswith("_") and k != "return"
                }
                wrapper.__annotations__["return"] = str
                return wrapper

            wrapped = _make_clean_wrapper(fn)

        decorated.append(tool()(wrapped))
    return decorated


def build_agent_tools(agent_name: str, agent_id: str = ""):
    """Build the standard MCP tool server for a space agent.

    Returns a server from create_sdk_mcp_server with tools 1-33.
    agent_id is the UUID needed for behavioral rule operations.
    """
    from claude_agent_sdk import create_sdk_mcp_server

    tools = _make_decorated_tools(_STANDARD_TOOLS, agent_name, agent_id)
    return create_sdk_mcp_server(f"openloop_{agent_name}", tools=tools)


def build_odin_tools(agent_id: str = ""):
    """Build the Odin-specific MCP tool server.

    Returns a server from create_sdk_mcp_server with standard tools (1-33)
    plus Odin-only tools (20-25).
    """
    from claude_agent_sdk import create_sdk_mcp_server

    all_tools = {**_STANDARD_TOOLS, **_ODIN_TOOLS}
    tools = _make_decorated_tools(all_tools, "odin", agent_id)
    return create_sdk_mcp_server("openloop_odin", tools=tools)


# Agent Builder-only tool registry
_AGENT_BUILDER_TOOLS = {
    "register_agent": register_agent,
    "test_agent": test_agent,
}


def build_agent_builder_tools(agent_name: str, agent_id: str = ""):
    """Build MCP tools for the Agent Builder agent.

    Standard tools + register_agent + test_agent (exclusive to Agent Builder).
    """
    from claude_agent_sdk import create_sdk_mcp_server

    all_tools = {**_STANDARD_TOOLS, **_AGENT_BUILDER_TOOLS}
    tools = _make_decorated_tools(all_tools, agent_name, agent_id)
    return create_sdk_mcp_server(f"openloop_{agent_name}", tools=tools)
