"""Tests for MCP tool functions.

Tests call the async tool functions directly with a test DB session injected
via the _db parameter. This avoids needing SessionLocal() and the real database.
"""

import json

import pytest
from sqlalchemy.orm import Session

from backend.openloop.agents.mcp_tools import (
    complete_todo,
    create_item,
    create_todo,
    get_board_state,
    list_spaces,
    list_todos,
    move_item,
    read_memory,
    write_memory,
)
from backend.openloop.services import space_service

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse(result: str) -> dict:
    """Parse a tool's JSON string return value."""
    return json.loads(result)


def _make_space(db: Session, name: str = "Test Space") -> str:
    """Create a space and return its ID."""
    space = space_service.create_space(db, name=name, template="project")
    return space.id


# ---------------------------------------------------------------------------
# To-do operations
# ---------------------------------------------------------------------------


class TestCreateTodo:
    @pytest.mark.asyncio
    async def test_create_todo_basic(self, db_session: Session):
        space_id = _make_space(db_session)
        result = _parse(await create_todo(space_id, "Buy groceries", _db=db_session))
        assert "result" in result
        assert result["result"]["title"] == "Buy groceries"
        assert result["result"]["space_id"] == space_id
        assert result["result"]["id"]

    @pytest.mark.asyncio
    async def test_create_todo_with_due_date(self, db_session: Session):
        space_id = _make_space(db_session)
        result = _parse(await create_todo(space_id, "Deadline task", "2025-06-15", _db=db_session))
        assert result["result"]["due_date"] == "2025-06-15T00:00:00"

    @pytest.mark.asyncio
    async def test_create_todo_bad_space(self, db_session: Session):
        result = _parse(await create_todo("nonexistent-id", "Orphan", _db=db_session))
        assert result["is_error"] is True
        assert "not found" in result["error"].lower()


class TestListTodos:
    @pytest.mark.asyncio
    async def test_list_todos_empty(self, db_session: Session):
        space_id = _make_space(db_session)
        result = _parse(await list_todos(space_id=space_id, _db=db_session))
        assert result["result"] == []

    @pytest.mark.asyncio
    async def test_list_todos_with_items(self, db_session: Session):
        space_id = _make_space(db_session)
        await create_todo(space_id, "Todo A", _db=db_session)
        await create_todo(space_id, "Todo B", _db=db_session)
        result = _parse(await list_todos(space_id=space_id, _db=db_session))
        assert len(result["result"]) == 2

    @pytest.mark.asyncio
    async def test_list_todos_filter_done(self, db_session: Session):
        space_id = _make_space(db_session)
        r = _parse(await create_todo(space_id, "Will be done", _db=db_session))
        todo_id = r["result"]["id"]
        await complete_todo(todo_id, _db=db_session)

        # Only pending
        result = _parse(await list_todos(space_id=space_id, is_done="false", _db=db_session))
        assert len(result["result"]) == 0

        # Only done
        result = _parse(await list_todos(space_id=space_id, is_done="true", _db=db_session))
        assert len(result["result"]) == 1
        assert result["result"][0]["is_done"] is True


# ---------------------------------------------------------------------------
# Board item operations
# ---------------------------------------------------------------------------


class TestCreateItem:
    @pytest.mark.asyncio
    async def test_create_item_basic(self, db_session: Session):
        space_id = _make_space(db_session)
        result = _parse(await create_item(space_id, "Build feature", _db=db_session))
        assert result["result"]["title"] == "Build feature"
        assert result["result"]["item_type"] == "task"
        # Default stage should be first board column for project template
        assert result["result"]["stage"] == "idea"

    @pytest.mark.asyncio
    async def test_create_item_with_stage(self, db_session: Session):
        space_id = _make_space(db_session)
        result = _parse(
            await create_item(space_id, "In progress item", stage="in_progress", _db=db_session)
        )
        assert result["result"]["stage"] == "in_progress"


class TestMoveItem:
    @pytest.mark.asyncio
    async def test_move_item(self, db_session: Session):
        space_id = _make_space(db_session)
        r = _parse(await create_item(space_id, "Movable", _db=db_session))
        item_id = r["result"]["id"]

        result = _parse(await move_item(item_id, "done", _db=db_session))
        assert result["result"]["stage"] == "done"

    @pytest.mark.asyncio
    async def test_move_item_invalid_stage(self, db_session: Session):
        space_id = _make_space(db_session)
        r = _parse(await create_item(space_id, "Movable", _db=db_session))
        item_id = r["result"]["id"]

        result = _parse(await move_item(item_id, "nonexistent_stage", _db=db_session))
        assert result["is_error"] is True
        assert "invalid stage" in result["error"].lower()


# ---------------------------------------------------------------------------
# Memory operations
# ---------------------------------------------------------------------------


class TestWriteMemory:
    @pytest.mark.asyncio
    async def test_write_and_read(self, db_session: Session):
        # Write
        w = _parse(await write_memory("test_ns", "greeting", "hello world", _db=db_session))
        assert w["result"]["namespace"] == "test_ns"
        assert w["result"]["key"] == "greeting"
        assert w["result"]["value"] == "hello world"

        # Read back
        r = _parse(await read_memory(namespace="test_ns", _db=db_session))
        assert len(r["result"]) == 1
        assert r["result"][0]["value"] == "hello world"

    @pytest.mark.asyncio
    async def test_write_with_tags(self, db_session: Session):
        w = _parse(await write_memory("ns", "k", "v", tags="a, b, c", _db=db_session))
        assert w["result"]["tags"] == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_upsert_overwrites(self, db_session: Session):
        await write_memory("ns", "key1", "original", _db=db_session)
        w2 = _parse(await write_memory("ns", "key1", "updated", _db=db_session))
        assert w2["result"]["value"] == "updated"

        r = _parse(await read_memory(namespace="ns", _db=db_session))
        assert len(r["result"]) == 1
        assert r["result"][0]["value"] == "updated"


class TestReadMemory:
    @pytest.mark.asyncio
    async def test_read_empty(self, db_session: Session):
        r = _parse(await read_memory(namespace="empty_ns", _db=db_session))
        assert r["result"] == []

    @pytest.mark.asyncio
    async def test_read_with_search(self, db_session: Session):
        await write_memory("ns", "color", "blue", _db=db_session)
        await write_memory("ns", "size", "large", _db=db_session)

        r = _parse(await read_memory(search="blue", _db=db_session))
        assert len(r["result"]) == 1
        assert r["result"][0]["key"] == "color"


# ---------------------------------------------------------------------------
# Context operations
# ---------------------------------------------------------------------------


class TestGetBoardState:
    @pytest.mark.asyncio
    async def test_board_state_empty(self, db_session: Session):
        space_id = _make_space(db_session)
        result = _parse(await get_board_state(space_id, _db=db_session))
        assert result["result"]["total_items"] == 0
        assert result["result"]["stages"] == {}

    @pytest.mark.asyncio
    async def test_board_state_with_items(self, db_session: Session):
        space_id = _make_space(db_session)
        await create_item(space_id, "Item A", stage="idea", _db=db_session)
        await create_item(space_id, "Item B", stage="idea", _db=db_session)
        await create_item(space_id, "Item C", stage="done", _db=db_session)

        result = _parse(await get_board_state(space_id, _db=db_session))
        assert result["result"]["total_items"] == 3
        assert len(result["result"]["stages"]["idea"]) == 2
        assert len(result["result"]["stages"]["done"]) == 1


# ---------------------------------------------------------------------------
# Odin-only tools
# ---------------------------------------------------------------------------


class TestListSpaces:
    @pytest.mark.asyncio
    async def test_list_spaces_empty(self, db_session: Session):
        result = _parse(await list_spaces(_db=db_session))
        assert result["result"] == []

    @pytest.mark.asyncio
    async def test_list_spaces_with_data(self, db_session: Session):
        _make_space(db_session, "Space A")
        _make_space(db_session, "Space B")
        result = _parse(await list_spaces(_db=db_session))
        assert len(result["result"]) == 2
        names = {s["name"] for s in result["result"]}
        assert names == {"Space A", "Space B"}
