"""MCP tool definitions for OpenLoop agents.

Each tool is an async function decorated with @tool(). Tools create their own
short-lived DB sessions via SessionLocal() (or an injected `_db` for testing).

All inputs arrive as strings from the SDK regardless of type annotation —
always coerce before use. All tools return JSON strings.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from backend.openloop.database import SessionLocal
from backend.openloop.services import (
    agent_service,
    conversation_service,
    document_service,
    item_service,
    memory_service,
    space_service,
    todo_service,
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


# ---------------------------------------------------------------------------
# Standard tools (1–19): available to all agents
# ---------------------------------------------------------------------------


# 1. create_todo
async def create_todo(
    space_id: str, title: str, due_date: str = "", *, _db=None, _agent_name: str = "agent"
) -> str:
    """Create a to-do in a space. due_date is optional ISO format (e.g. 2025-01-15)."""
    db = _get_db(_db)
    try:
        todo = todo_service.create_todo(
            db,
            space_id=space_id,
            title=title,
            due_date=_parse_date(due_date),
            created_by=_agent_name,
        )
        return _ok(
            {
                "id": todo.id,
                "title": todo.title,
                "space_id": todo.space_id,
                "due_date": todo.due_date.isoformat() if todo.due_date else None,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 2. complete_todo
async def complete_todo(todo_id: str, *, _db=None) -> str:
    """Mark a to-do as done."""
    db = _get_db(_db)
    try:
        todo = todo_service.update_todo(db, todo_id, is_done=True)
        return _ok({"id": todo.id, "title": todo.title, "is_done": True})
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 3. list_todos
async def list_todos(space_id: str = "", is_done: str = "", *, _db=None) -> str:
    """List to-dos. Empty string = no filter. is_done: 'true'/'false'/''."""
    db = _get_db(_db)
    try:
        todos = todo_service.list_todos(
            db,
            space_id=space_id or None,
            is_done=_parse_bool(is_done),
        )
        return _ok(
            [
                {
                    "id": t.id,
                    "title": t.title,
                    "is_done": t.is_done,
                    "space_id": t.space_id,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                }
                for t in todos
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
    *,
    _db=None,
    _agent_name: str = "agent",
) -> str:
    """Create a board item (task or record) in a space."""
    db = _get_db(_db)
    try:
        item = item_service.create_item(
            db,
            space_id=space_id,
            title=title,
            item_type=item_type or "task",
            stage=stage or None,
            description=description or None,
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
) -> str:
    """Update board item fields. Empty string = don't change."""
    db = _get_db(_db)
    try:
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
async def move_item(item_id: str, stage: str, *, _db=None, _agent_name: str = "agent") -> str:
    """Move a board item to a different stage."""
    db = _get_db(_db)
    try:
        item = item_service.move_item(db, item_id, stage, triggered_by=_agent_name)
        return _ok({"id": item.id, "title": item.title, "stage": item.stage})
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 7. get_item
async def get_item(item_id: str, *, _db=None) -> str:
    """Get full details of a board item."""
    db = _get_db(_db)
    try:
        item = item_service.get_item(db, item_id)
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
    space_id: str = "", stage: str = "", item_type: str = "", limit: str = "20", *, _db=None
) -> str:
    """List board items with optional filters."""
    db = _get_db(_db)
    try:
        limit_int = _parse_int(limit, 20)
        items = item_service.list_items(
            db,
            space_id=space_id or None,
            stage=stage or None,
            item_type=item_type or None,
        )
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


# 11. read_document
async def read_document(document_id: str, *, _db=None) -> str:
    """Get document metadata by ID."""
    db = _get_db(_db)
    try:
        doc = document_service.get_document(db, document_id)
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
async def list_documents(space_id: str = "", search: str = "", *, _db=None) -> str:
    """List documents with optional space filter and title search."""
    db = _get_db(_db)
    try:
        docs = document_service.list_documents(
            db,
            space_id=space_id or None,
            search=search or None,
        )
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
    space_id: str, title: str, source: str = "local", tags: str = "", *, _db=None
) -> str:
    """Index a document in a space. tags is comma-separated."""
    db = _get_db(_db)
    try:
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
async def get_board_state(space_id: str, *, _db=None) -> str:
    """Get a summary of all board items grouped by stage."""
    db = _get_db(_db)
    try:
        space = space_service.get_space(db, space_id)
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


# 15. get_todo_state
async def get_todo_state(space_id: str = "", *, _db=None) -> str:
    """Get summary of to-dos: counts by status, overdue items."""
    db = _get_db(_db)
    try:
        all_todos = todo_service.list_todos(db, space_id=space_id or None, limit=10000)
        done = [t for t in all_todos if t.is_done]
        pending = [t for t in all_todos if not t.is_done]
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
                "total": len(all_todos),
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
async def get_conversation_summaries(space_id: str, limit: str = "5", *, _db=None) -> str:
    """Get recent conversation summaries for a space."""
    db = _get_db(_db)
    try:
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
async def search_conversations(space_id: str, query: str = "", *, _db=None) -> str:
    """Search conversation messages using basic LIKE matching."""
    from backend.openloop.db.models import Conversation, ConversationMessage

    db = _get_db(_db)
    try:
        q = db.query(ConversationMessage).join(Conversation)
        q = q.filter(Conversation.space_id == space_id)
        if query:
            pattern = f"%{query}%"
            q = q.filter(ConversationMessage.content.ilike(pattern))
        messages = q.order_by(ConversationMessage.created_at.desc()).limit(20).all()
        return _ok(
            [
                {
                    "message_id": m.id,
                    "conversation_id": m.conversation_id,
                    "role": m.role,
                    "content": m.content[:200],
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
async def delegate_task(agent_name: str, instruction: str, space_id: str = "", *, _db=None) -> str:
    """Delegate a task to another agent. (Not yet implemented — Phase 5.)"""
    return _ok(
        {
            "status": "not_implemented",
            "message": (
                f"Delegation to agent '{agent_name}' is not yet implemented. "
                "This feature is planned for Phase 5."
            ),
        }
    )


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
    space_id: str, agent_id: str, initial_message: str = "", model: str = "", *, _db=None
) -> str:
    """Create a new conversation. Returns routing info for the frontend."""
    db = _get_db(_db)
    try:
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
async def navigate_to_space(space_id: str, *, _db=None) -> str:
    """Returns a navigation instruction for the frontend."""
    db = _get_db(_db)
    try:
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

        # Overdue to-dos
        now = datetime.now(UTC)
        all_todos = todo_service.list_todos(db, is_done=False, limit=10000)
        overdue = [
            {
                "id": t.id,
                "title": t.title,
                "space_id": t.space_id,
                "due_date": t.due_date.isoformat(),
            }
            for t in all_todos
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
            for t in all_todos
            if t.due_date and today_start <= t.due_date <= today_end
        ]

        return _ok(
            {
                "pending_approvals": pending_approvals,
                "overdue_todos": overdue,
                "due_today": due_today,
            }
        )
    except Exception as e:
        db.rollback()
        return _err(str(e))
    finally:
        if _db is None:
            db.close()


# 25. get_cross_space_todos
async def get_cross_space_todos(is_done: str = "", *, _db=None) -> str:
    """Get to-dos across all spaces."""
    db = _get_db(_db)
    try:
        todos = todo_service.list_todos(db, is_done=_parse_bool(is_done))
        return _ok(
            [
                {
                    "id": t.id,
                    "title": t.title,
                    "is_done": t.is_done,
                    "space_id": t.space_id,
                    "due_date": t.due_date.isoformat() if t.due_date else None,
                }
                for t in todos
            ]
        )
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
    "create_todo": create_todo,
    "complete_todo": complete_todo,
    "list_todos": list_todos,
    "create_item": create_item,
    "update_item": update_item,
    "move_item": move_item,
    "get_item": get_item,
    "list_items": list_items,
    "read_memory": read_memory,
    "write_memory": write_memory,
    "read_document": read_document,
    "list_documents": list_documents,
    "create_document": create_document,
    "get_board_state": get_board_state,
    "get_todo_state": get_todo_state,
    "get_conversation_summaries": get_conversation_summaries,
    "search_conversations": search_conversations,
    "get_conversation_messages": get_conversation_messages,
    "delegate_task": delegate_task,
}

_ODIN_TOOLS = {
    "list_spaces": list_spaces,
    "list_agents": list_agents,
    "open_conversation": open_conversation,
    "navigate_to_space": navigate_to_space,
    "get_attention_items": get_attention_items,
    "get_cross_space_todos": get_cross_space_todos,
}


def _make_decorated_tools(tool_map: dict, agent_name: str) -> list:
    """Wrap raw async functions with @tool() and inject _agent_name via closures."""
    from claude_agent_sdk import tool

    decorated = []
    for name, fn in tool_map.items():
        # Build a closure that binds agent_name for tools that support it
        import inspect

        sig = inspect.signature(fn)
        has_agent_name = "_agent_name" in sig.parameters

        if has_agent_name:
            # Create closure binding agent_name
            def _make_wrapper(original_fn, bound_name):
                async def wrapper(**kwargs):
                    kwargs["_agent_name"] = bound_name
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

            wrapped = _make_wrapper(fn, agent_name)
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


def build_agent_tools(agent_name: str):
    """Build the standard MCP tool server for a space agent.

    Returns a server from create_sdk_mcp_server with tools 1-19.
    """
    from claude_agent_sdk import create_sdk_mcp_server

    tools = _make_decorated_tools(_STANDARD_TOOLS, agent_name)
    return create_sdk_mcp_server(f"openloop_{agent_name}", tools=tools)


def build_odin_tools():
    """Build the Odin-specific MCP tool server.

    Returns a server from create_sdk_mcp_server with standard tools (1-19)
    plus Odin-only tools (20-25).
    """
    from claude_agent_sdk import create_sdk_mcp_server

    all_tools = {**_STANDARD_TOOLS, **_ODIN_TOOLS}
    tools = _make_decorated_tools(all_tools, "odin")
    return create_sdk_mcp_server("openloop_odin", tools=tools)
