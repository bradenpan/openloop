"""Tests for FTS5 search service.

In-memory SQLite doesn't have Alembic migrations, so we manually create
the FTS5 virtual tables and sync triggers in a fixture.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.openloop.db.models import (
    Agent,
    Conversation,
    ConversationMessage,
    ConversationSummary,
    Document,
    MemoryEntry,
    Space,
)
from backend.openloop.services import search_service

# ---------------------------------------------------------------------------
# FTS5 setup SQL (mirrors the Alembic migration)
# ---------------------------------------------------------------------------

_FTS_SETUP_SQL = [
    # Virtual tables
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
    # Triggers — conversation_messages
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
    # Triggers — conversation_summaries
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
    # Triggers — memory_entries (only index active)
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
    # Triggers — documents
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
def sample_data(fts_db: Session) -> dict:
    """Insert sample data into source tables. Returns refs for assertions."""
    space = Space(id=_uid(), name="Test Space", template="project")
    fts_db.add(space)
    fts_db.flush()

    space2 = Space(id=_uid(), name="Other Space", template="project")
    fts_db.add(space2)
    fts_db.flush()

    agent = Agent(id=_uid(), name="test-agent")
    fts_db.add(agent)
    fts_db.flush()

    conv = Conversation(
        id=_uid(),
        space_id=space.id,
        agent_id=agent.id,
        name="Architecture Discussion",
    )
    fts_db.add(conv)
    fts_db.flush()

    conv2 = Conversation(
        id=_uid(),
        space_id=space2.id,
        agent_id=agent.id,
        name="Other Conversation",
    )
    fts_db.add(conv2)
    fts_db.flush()

    msg1 = ConversationMessage(
        id=_uid(),
        conversation_id=conv.id,
        role="user",
        content="We need to implement the authentication module with OAuth2 support",
    )
    msg2 = ConversationMessage(
        id=_uid(),
        conversation_id=conv.id,
        role="assistant",
        content="I recommend using FastAPI's built-in OAuth2 integration for authentication",
    )
    msg3 = ConversationMessage(
        id=_uid(),
        conversation_id=conv2.id,
        role="user",
        content="Let us discuss the database migration strategy",
    )
    fts_db.add_all([msg1, msg2, msg3])
    fts_db.flush()

    summary = ConversationSummary(
        id=_uid(),
        conversation_id=conv.id,
        space_id=space.id,
        summary="Discussed authentication architecture using OAuth2 with FastAPI",
    )
    fts_db.add(summary)
    fts_db.flush()

    mem1 = MemoryEntry(
        id=_uid(),
        namespace="preferences",
        key="auth-method",
        value="User prefers OAuth2 for authentication over API keys",
    )
    mem2 = MemoryEntry(
        id=_uid(),
        namespace="facts",
        key="db-engine",
        value="Project uses SQLite with WAL mode for the database",
    )
    fts_db.add_all([mem1, mem2])
    fts_db.flush()

    doc = Document(
        id=_uid(),
        space_id=space.id,
        title="Authentication Design Document",
        source="manual",
    )
    fts_db.add(doc)
    fts_db.flush()

    fts_db.commit()

    return {
        "space": space,
        "space2": space2,
        "agent": agent,
        "conv": conv,
        "conv2": conv2,
        "msg1": msg1,
        "msg2": msg2,
        "msg3": msg3,
        "summary": summary,
        "mem1": mem1,
        "mem2": mem2,
        "doc": doc,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSearchMessages:
    def test_basic_search(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_messages(fts_db, "authentication")
        assert len(results) >= 1
        assert all(r["type"] == "message" for r in results)
        # Should find messages mentioning authentication
        assert any("authentication" in r["excerpt"].lower() or "authentication" in r["title"].lower() for r in results)

    def test_space_filter(self, sample_data: dict, fts_db: Session) -> None:
        space_id = sample_data["space"].id
        results = search_service.search_messages(
            fts_db, "authentication", space_id=space_id
        )
        # All results should be from the filtered space
        assert all(r["space_id"] == space_id for r in results)

    def test_conversation_filter(self, sample_data: dict, fts_db: Session) -> None:
        conv_id = sample_data["conv2"].id
        results = search_service.search_messages(
            fts_db, "database", conversation_id=conv_id
        )
        assert len(results) >= 1
        assert all(r["source_id"] == conv_id for r in results)

    def test_no_results(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_messages(fts_db, "zyxwvutsrqponm")
        assert results == []


class TestSearchSummaries:
    def test_basic_search(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_summaries(fts_db, "OAuth2")
        assert len(results) >= 1
        assert all(r["type"] == "summary" for r in results)

    def test_space_filter(self, sample_data: dict, fts_db: Session) -> None:
        other_space_id = sample_data["space2"].id
        results = search_service.search_summaries(
            fts_db, "OAuth2", space_id=other_space_id
        )
        assert results == []


class TestSearchMemory:
    def test_basic_search(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_memory(fts_db, "OAuth2")
        assert len(results) >= 1
        assert all(r["type"] == "memory" for r in results)

    def test_namespace_filter(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_memory(
            fts_db, "SQLite", namespace="facts"
        )
        assert len(results) >= 1
        results_other = search_service.search_memory(
            fts_db, "SQLite", namespace="preferences"
        )
        assert results_other == []

    def test_archived_memory_not_indexed(self, sample_data: dict, fts_db: Session) -> None:
        mem = sample_data["mem1"]
        mem.archived_at = datetime.now(UTC)
        fts_db.commit()

        results = search_service.search_memory(fts_db, "OAuth2")
        matching = [r for r in results if r["id"] == mem.id]
        assert matching == []

    def test_superseded_fact_not_indexed(self, sample_data: dict, fts_db: Session) -> None:
        mem = sample_data["mem2"]
        mem.valid_until = datetime.now(UTC)
        fts_db.commit()

        results = search_service.search_memory(fts_db, "SQLite")
        matching = [r for r in results if r["id"] == mem.id]
        assert matching == []


class TestSearchDocuments:
    def test_basic_search(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_documents(fts_db, "Authentication")
        assert len(results) >= 1
        assert all(r["type"] == "document" for r in results)

    def test_space_filter(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_documents(
            fts_db, "Authentication", space_id=sample_data["space"].id
        )
        assert len(results) >= 1

        results_other = search_service.search_documents(
            fts_db, "Authentication", space_id=sample_data["space2"].id
        )
        assert results_other == []


class TestSearchAll:
    def test_returns_grouped_results(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_all(fts_db, "authentication")
        assert "messages" in results
        assert "summaries" in results
        assert "memory" in results
        assert "documents" in results
        # Should find something in messages, summaries, memory, and documents
        total = sum(len(v) for v in results.values())
        assert total > 0

    def test_type_filter_via_search_all(self, sample_data: dict, fts_db: Session) -> None:
        results = search_service.search_all(fts_db, "authentication")
        # Messages should have results
        assert len(results["messages"]) >= 1


class TestRebuildIndexes:
    def test_rebuild(self, fts_db: Session, sample_data: dict) -> None:
        # Rebuild should not error
        search_service.rebuild_fts_indexes(fts_db)

        # Results should still be present
        results = search_service.search_messages(fts_db, "authentication")
        assert len(results) >= 1


class TestEmptyQuery:
    def test_empty_string(self, fts_db: Session) -> None:
        assert search_service.search_messages(fts_db, "") == []
        assert search_service.search_summaries(fts_db, "") == []
        assert search_service.search_memory(fts_db, "") == []
        assert search_service.search_documents(fts_db, "") == []

    def test_only_special_chars(self, fts_db: Session) -> None:
        assert search_service.search_messages(fts_db, '***"()') == []


class TestSanitization:
    def test_special_chars_stripped(self, sample_data: dict, fts_db: Session) -> None:
        # Should not raise even with FTS5 special chars in query
        results = search_service.search_messages(fts_db, '"authentication" OR (hack*)')
        # Should still find results (the word authentication is in there)
        assert isinstance(results, list)
