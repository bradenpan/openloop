"""Tests for FTS5-backed MCP search tools.

Verifies search_conversations, search_summaries, and recall_facts
all use FTS5, support cross-space search, and respect permission scoping.
"""

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.openloop.agents.mcp_tools import (
    _get_agent_space_ids,
    recall_facts,
    search_conversations,
    search_summaries,
)
from backend.openloop.db.models import (
    Agent,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    MemoryEntry,
    Space,
)

# ---------------------------------------------------------------------------
# FTS5 setup SQL (same as test_search_service.py)
# ---------------------------------------------------------------------------

_FTS_SETUP_SQL = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversation_messages
    USING fts5(content, content='conversation_messages', content_rowid='rowid');
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversation_summaries
    USING fts5(summary, content='conversation_summaries', content_rowid='rowid');
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_memory_entries
    USING fts5(value, content='memory_entries', content_rowid='rowid');
    """,
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents
    USING fts5(title, content='documents', content_rowid='rowid');
    """,
    # Triggers -- conversation_messages
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_ai
    AFTER INSERT ON conversation_messages
    BEGIN
        INSERT INTO fts_conversation_messages(rowid, content)
        VALUES (new.rowid, new.content);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_bd
    BEFORE DELETE ON conversation_messages
    BEGIN
        INSERT INTO fts_conversation_messages(fts_conversation_messages, rowid, content)
        VALUES ('delete', old.rowid, old.content);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_au
    AFTER UPDATE ON conversation_messages
    BEGIN
        INSERT INTO fts_conversation_messages(fts_conversation_messages, rowid, content)
        VALUES ('delete', old.rowid, old.content);
        INSERT INTO fts_conversation_messages(rowid, content)
        VALUES (new.rowid, new.content);
    END;
    """,
    # Triggers -- conversation_summaries
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_ai
    AFTER INSERT ON conversation_summaries
    BEGIN
        INSERT INTO fts_conversation_summaries(rowid, summary)
        VALUES (new.rowid, new.summary);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_bd
    BEFORE DELETE ON conversation_summaries
    BEGIN
        INSERT INTO fts_conversation_summaries(fts_conversation_summaries, rowid, summary)
        VALUES ('delete', old.rowid, old.summary);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_au
    AFTER UPDATE ON conversation_summaries
    BEGIN
        INSERT INTO fts_conversation_summaries(fts_conversation_summaries, rowid, summary)
        VALUES ('delete', old.rowid, old.summary);
        INSERT INTO fts_conversation_summaries(rowid, summary)
        VALUES (new.rowid, new.summary);
    END;
    """,
    # Triggers -- memory_entries
    """
    CREATE TRIGGER IF NOT EXISTS fts_memory_entries_ai
    AFTER INSERT ON memory_entries
    WHEN new.archived_at IS NULL AND new.valid_until IS NULL
    BEGIN
        INSERT INTO fts_memory_entries(rowid, value)
        VALUES (new.rowid, new.value);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_memory_entries_bd
    BEFORE DELETE ON memory_entries
    BEGIN
        INSERT INTO fts_memory_entries(fts_memory_entries, rowid, value)
        VALUES ('delete', old.rowid, old.value);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_memory_entries_au
    AFTER UPDATE ON memory_entries
    BEGIN
        INSERT INTO fts_memory_entries(fts_memory_entries, rowid, value)
        VALUES ('delete', old.rowid, old.value);
        INSERT INTO fts_memory_entries(rowid, value)
        SELECT new.rowid, new.value
        WHERE new.archived_at IS NULL AND new.valid_until IS NULL;
    END;
    """,
    # Triggers -- documents
    """
    CREATE TRIGGER IF NOT EXISTS fts_documents_ai
    AFTER INSERT ON documents
    BEGIN
        INSERT INTO fts_documents(rowid, title)
        VALUES (new.rowid, new.title);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_documents_bd
    BEFORE DELETE ON documents
    BEGIN
        INSERT INTO fts_documents(fts_documents, rowid, title)
        VALUES ('delete', old.rowid, old.title);
    END;
    """,
    """
    CREATE TRIGGER IF NOT EXISTS fts_documents_au
    AFTER UPDATE ON documents
    BEGIN
        INSERT INTO fts_documents(fts_documents, rowid, title)
        VALUES ('delete', old.rowid, old.title);
        INSERT INTO fts_documents(rowid, title)
        VALUES (new.rowid, new.title);
    END;
    """,
]

_FTS_TEARDOWN_TRIGGERS = [
    "fts_conversation_messages_ai",
    "fts_conversation_messages_bd",
    "fts_conversation_messages_au",
    "fts_conversation_summaries_ai",
    "fts_conversation_summaries_bd",
    "fts_conversation_summaries_au",
    "fts_memory_entries_ai",
    "fts_memory_entries_bd",
    "fts_memory_entries_au",
    "fts_documents_ai",
    "fts_documents_bd",
    "fts_documents_au",
]

_FTS_TEARDOWN_TABLES = [
    "fts_conversation_messages",
    "fts_conversation_summaries",
    "fts_memory_entries",
    "fts_documents",
]


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def fts_db(db_session: Session) -> Session:
    """Create FTS5 tables and triggers, yield session, clean up after."""
    conn = db_session.connection()
    for sql in _FTS_SETUP_SQL:
        conn.execute(text(sql))
    db_session.commit()

    yield db_session

    # Teardown
    conn = db_session.connection()
    for name in _FTS_TEARDOWN_TRIGGERS:
        conn.execute(text(f"DROP TRIGGER IF EXISTS {name};"))
    for table in _FTS_TEARDOWN_TABLES:
        conn.execute(text(f"DROP TABLE IF EXISTS {table};"))
    db_session.commit()


@pytest.fixture()
def search_data(fts_db: Session) -> dict:
    """Set up multi-space data with agents and permission scoping."""
    # Two spaces
    space_a = Space(id=_uid(), name="Engineering", template="project")
    space_b = Space(id=_uid(), name="Marketing", template="project")
    fts_db.add_all([space_a, space_b])
    fts_db.flush()

    # Two agents: scoped agent (only space_a) and system agent (Odin, no restrictions)
    scoped_agent = Agent(id=_uid(), name="eng-agent")
    odin = Agent(id=_uid(), name="odin")
    fts_db.add_all([scoped_agent, odin])
    fts_db.flush()

    # Grant scoped_agent access to space_a only
    fts_db.execute(
        text("INSERT INTO agent_spaces (agent_id, space_id) VALUES (:aid, :sid)"),
        {"aid": scoped_agent.id, "sid": space_a.id},
    )
    fts_db.flush()

    # Conversations in both spaces
    conv_a = Conversation(
        id=_uid(),
        space_id=space_a.id,
        agent_id=scoped_agent.id,
        name="Backend Architecture",
    )
    conv_b = Conversation(
        id=_uid(),
        space_id=space_b.id,
        agent_id=odin.id,
        name="Marketing Strategy",
    )
    fts_db.add_all([conv_a, conv_b])
    fts_db.flush()

    # Messages in space A
    msg_a1 = ConversationMessage(
        id=_uid(),
        conversation_id=conv_a.id,
        role="user",
        content="We should implement the authentication module using OAuth2 tokens",
    )
    msg_a2 = ConversationMessage(
        id=_uid(),
        conversation_id=conv_a.id,
        role="assistant",
        content="I recommend FastAPI OAuth2 integration for the authentication flow",
    )
    # Messages in space B
    msg_b1 = ConversationMessage(
        id=_uid(),
        conversation_id=conv_b.id,
        role="user",
        content="We need a new authentication strategy for our marketing platform",
    )
    fts_db.add_all([msg_a1, msg_a2, msg_b1])
    fts_db.flush()

    # Summaries
    summary_a = ConversationSummary(
        id=_uid(),
        conversation_id=conv_a.id,
        space_id=space_a.id,
        summary="Discussed authentication architecture using OAuth2 with FastAPI for the backend",
    )
    summary_b = ConversationSummary(
        id=_uid(),
        conversation_id=conv_b.id,
        space_id=space_b.id,
        summary="Planned authentication strategy for new marketing platform launch",
    )
    fts_db.add_all([summary_a, summary_b])
    fts_db.flush()

    # Memory entries
    mem1 = MemoryEntry(
        id=_uid(),
        namespace="preferences",
        key="auth-method",
        value="User prefers OAuth2 for authentication over API keys",
        importance=0.8,
        category="preference",
    )
    mem2 = MemoryEntry(
        id=_uid(),
        namespace="facts",
        key="db-engine",
        value="Project uses SQLite with WAL mode for the database engine",
        importance=0.6,
        category="technical",
    )
    fts_db.add_all([mem1, mem2])
    fts_db.flush()

    fts_db.commit()

    return {
        "space_a": space_a,
        "space_b": space_b,
        "scoped_agent": scoped_agent,
        "odin": odin,
        "conv_a": conv_a,
        "conv_b": conv_b,
        "msg_a1": msg_a1,
        "msg_a2": msg_a2,
        "msg_b1": msg_b1,
        "summary_a": summary_a,
        "summary_b": summary_b,
        "mem1": mem1,
        "mem2": mem2,
    }


# ---------------------------------------------------------------------------
# Helper: parse MCP tool JSON response
# ---------------------------------------------------------------------------


def _parse(raw: str) -> dict:
    return json.loads(raw)


def _result(raw: str) -> list | dict:
    parsed = _parse(raw)
    assert "is_error" not in parsed, f"Tool returned error: {parsed.get('error')}"
    return parsed["result"]


# ---------------------------------------------------------------------------
# Tests: _get_agent_space_ids
# ---------------------------------------------------------------------------


class TestGetAgentSpaceIds:
    def test_scoped_agent_returns_space_list(self, search_data: dict, fts_db: Session) -> None:
        agent = search_data["scoped_agent"]
        space_ids = _get_agent_space_ids(fts_db, agent.id)
        assert space_ids is not None
        assert search_data["space_a"].id in space_ids
        assert search_data["space_b"].id not in space_ids

    def test_system_agent_returns_none(self, search_data: dict, fts_db: Session) -> None:
        """Odin has no agent_spaces rows, so returns None (unrestricted)."""
        odin = search_data["odin"]
        space_ids = _get_agent_space_ids(fts_db, odin.id)
        assert space_ids is None

    def test_empty_agent_id_returns_none(self, fts_db: Session) -> None:
        space_ids = _get_agent_space_ids(fts_db, "")
        assert space_ids is None


# ---------------------------------------------------------------------------
# Tests: search_conversations (FTS5 upgrade)
# ---------------------------------------------------------------------------


class TestSearchConversations:
    @pytest.mark.asyncio
    async def test_basic_fts_search(self, search_data: dict, fts_db: Session) -> None:
        """FTS5 search returns results with relevance scores."""
        raw = await search_conversations(
            query="authentication",
            space_id=search_data["space_a"].id,
            _db=fts_db,
            _agent_id=search_data["scoped_agent"].id,
        )
        results = _result(raw)
        assert len(results) >= 1
        assert all("relevance_score" in r for r in results)
        assert all(r["relevance_score"] > 0 for r in results)

    @pytest.mark.asyncio
    async def test_space_scoping(self, search_data: dict, fts_db: Session) -> None:
        """When space_id is provided, only results from that space appear."""
        raw = await search_conversations(
            query="authentication",
            space_id=search_data["space_a"].id,
            _db=fts_db,
            _agent_id=search_data["scoped_agent"].id,
        )
        results = _result(raw)
        assert len(results) >= 1
        assert all(r["space_id"] == search_data["space_a"].id for r in results)

    @pytest.mark.asyncio
    async def test_cross_space_scoped_agent(self, search_data: dict, fts_db: Session) -> None:
        """Scoped agent without space_id sees only its permitted spaces."""
        raw = await search_conversations(
            query="authentication",
            _db=fts_db,
            _agent_id=search_data["scoped_agent"].id,
        )
        results = _result(raw)
        assert len(results) >= 1
        # Should only contain results from space_a (the agent's permitted space)
        for r in results:
            assert r["space_id"] == search_data["space_a"].id

    @pytest.mark.asyncio
    async def test_cross_space_odin_sees_all(self, search_data: dict, fts_db: Session) -> None:
        """Odin (system agent) without space_id sees results from all spaces."""
        raw = await search_conversations(
            query="authentication",
            _db=fts_db,
            _agent_id=search_data["odin"].id,
        )
        results = _result(raw)
        space_ids_in_results = {r["space_id"] for r in results}
        # Odin should see results from both spaces
        assert search_data["space_a"].id in space_ids_in_results
        assert search_data["space_b"].id in space_ids_in_results

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, search_data: dict, fts_db: Session) -> None:
        raw = await search_conversations(
            query="",
            _db=fts_db,
            _agent_id=search_data["scoped_agent"].id,
        )
        results = _result(raw)
        assert results == []

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, search_data: dict, fts_db: Session) -> None:
        raw = await search_conversations(
            query="zyxwvutsrqponm",
            _db=fts_db,
            _agent_id=search_data["scoped_agent"].id,
        )
        results = _result(raw)
        assert results == []

    @pytest.mark.asyncio
    async def test_conversation_id_filter(self, search_data: dict, fts_db: Session) -> None:
        """Filter results to a specific conversation."""
        raw = await search_conversations(
            query="authentication",
            conversation_id=search_data["conv_a"].id,
            _db=fts_db,
            _agent_id=search_data["odin"].id,
        )
        results = _result(raw)
        assert len(results) >= 1
        assert all(r["conversation_id"] == search_data["conv_a"].id for r in results)


# ---------------------------------------------------------------------------
# Tests: search_summaries (new tool)
# ---------------------------------------------------------------------------


class TestSearchSummaries:
    @pytest.mark.asyncio
    async def test_basic_search(self, search_data: dict, fts_db: Session) -> None:
        raw = await search_summaries(
            query="authentication",
            _db=fts_db,
            _agent_id=search_data["odin"].id,
        )
        results = _result(raw)
        assert len(results) >= 1
        assert all("relevance_score" in r for r in results)
        assert all("summary_id" in r for r in results)
        assert all("conversation_name" in r for r in results)

    @pytest.mark.asyncio
    async def test_space_filter(self, search_data: dict, fts_db: Session) -> None:
        raw = await search_summaries(
            query="authentication",
            space_id=search_data["space_a"].id,
            _db=fts_db,
            _agent_id=search_data["scoped_agent"].id,
        )
        results = _result(raw)
        assert len(results) >= 1
        assert all(r["space_id"] == search_data["space_a"].id for r in results)

    @pytest.mark.asyncio
    async def test_cross_space_scoped_agent(self, search_data: dict, fts_db: Session) -> None:
        """Scoped agent sees summaries only from permitted spaces."""
        raw = await search_summaries(
            query="authentication",
            _db=fts_db,
            _agent_id=search_data["scoped_agent"].id,
        )
        results = _result(raw)
        assert len(results) >= 1
        for r in results:
            assert r["space_id"] == search_data["space_a"].id

    @pytest.mark.asyncio
    async def test_cross_space_odin(self, search_data: dict, fts_db: Session) -> None:
        """Odin sees summaries from all spaces."""
        raw = await search_summaries(
            query="authentication",
            _db=fts_db,
            _agent_id=search_data["odin"].id,
        )
        results = _result(raw)
        space_ids_in_results = {r["space_id"] for r in results}
        assert search_data["space_a"].id in space_ids_in_results
        assert search_data["space_b"].id in space_ids_in_results

    @pytest.mark.asyncio
    async def test_empty_query(self, search_data: dict, fts_db: Session) -> None:
        raw = await search_summaries(
            query="",
            _db=fts_db,
            _agent_id=search_data["odin"].id,
        )
        results = _result(raw)
        assert results == []


# ---------------------------------------------------------------------------
# Tests: recall_facts (FTS5 upgrade)
# ---------------------------------------------------------------------------


class TestRecallFacts:
    @pytest.mark.asyncio
    async def test_fts_search(self, search_data: dict, fts_db: Session) -> None:
        """FTS5 search returns memory results with relevance scores."""
        raw = await recall_facts(query="OAuth2", _db=fts_db)
        results = _result(raw)
        assert len(results) >= 1
        assert all("relevance_score" in r for r in results)
        assert all(r["relevance_score"] > 0 for r in results)

    @pytest.mark.asyncio
    async def test_fts_with_namespace_filter(self, search_data: dict, fts_db: Session) -> None:
        raw = await recall_facts(query="OAuth2", namespace="preferences", _db=fts_db)
        results = _result(raw)
        assert len(results) >= 1
        # All results should be from the preferences namespace
        for r in results:
            assert r["namespace"] == "preferences"

    @pytest.mark.asyncio
    async def test_fts_with_category_filter(self, search_data: dict, fts_db: Session) -> None:
        raw = await recall_facts(query="OAuth2", category="preference", _db=fts_db)
        results = _result(raw)
        assert len(results) >= 1
        for r in results:
            assert r["category"] == "preference"

    @pytest.mark.asyncio
    async def test_namespace_only_returns_scored(self, search_data: dict, fts_db: Session) -> None:
        """When only namespace is given, falls back to importance-based scoring."""
        raw = await recall_facts(namespace="preferences", _db=fts_db)
        results = _result(raw)
        assert len(results) >= 1
        assert all("importance" in r for r in results)

    @pytest.mark.asyncio
    async def test_no_query_no_namespace(self, search_data: dict, fts_db: Session) -> None:
        """No query and no namespace returns all entries."""
        raw = await recall_facts(_db=fts_db)
        results = _result(raw)
        assert len(results) >= 2  # We inserted 2 memory entries

    @pytest.mark.asyncio
    async def test_no_match(self, search_data: dict, fts_db: Session) -> None:
        raw = await recall_facts(query="zyxwvutsrqponm", _db=fts_db)
        results = _result(raw)
        assert results == []

    @pytest.mark.asyncio
    async def test_recall_is_read_only(self, search_data: dict, fts_db: Session) -> None:
        """FTS5 recall should NOT modify entries (read-only operation)."""
        mem = search_data["mem1"]
        original_count = mem.access_count

        await recall_facts(query="OAuth2", _db=fts_db)

        fts_db.refresh(mem)
        assert mem.access_count == original_count
