"""FTS5 search infrastructure

Create FTS5 virtual tables and sync triggers for full-text search
across conversation_messages, conversation_summaries, memory_entries,
and documents.

Revision ID: fts5_search
Revises: b4c2_doc_mgmt
Create Date: 2026-03-31
"""

from collections.abc import Sequence

from alembic import op

revision: str = "fts5_search"
down_revision: str | None = "b4c2_doc_mgmt"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. FTS5 virtual tables (external content)
    # -----------------------------------------------------------------------

    # conversation_messages → content
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversation_messages
        USING fts5(content, content='conversation_messages', content_rowid='rowid');
        """
    )

    # conversation_summaries → summary
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_conversation_summaries
        USING fts5(summary, content='conversation_summaries', content_rowid='rowid');
        """
    )

    # memory_entries → value
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_memory_entries
        USING fts5(value, content='memory_entries', content_rowid='rowid');
        """
    )

    # documents → title + content_text
    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_documents
        USING fts5(title, content_text, content='documents', content_rowid='rowid');
        """
    )

    # -----------------------------------------------------------------------
    # 2. Triggers — conversation_messages
    # -----------------------------------------------------------------------

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_ai
        AFTER INSERT ON conversation_messages
        BEGIN
            INSERT INTO fts_conversation_messages(rowid, content)
            VALUES (new.rowid, new.content);
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_bd
        BEFORE DELETE ON conversation_messages
        BEGIN
            INSERT INTO fts_conversation_messages(fts_conversation_messages, rowid, content)
            VALUES ('delete', old.rowid, old.content);
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_conversation_messages_au
        AFTER UPDATE ON conversation_messages
        BEGIN
            INSERT INTO fts_conversation_messages(fts_conversation_messages, rowid, content)
            VALUES ('delete', old.rowid, old.content);
            INSERT INTO fts_conversation_messages(rowid, content)
            VALUES (new.rowid, new.content);
        END;
        """
    )

    # -----------------------------------------------------------------------
    # 3. Triggers — conversation_summaries
    # -----------------------------------------------------------------------

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_ai
        AFTER INSERT ON conversation_summaries
        BEGIN
            INSERT INTO fts_conversation_summaries(rowid, summary)
            VALUES (new.rowid, new.summary);
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_bd
        BEFORE DELETE ON conversation_summaries
        BEGIN
            INSERT INTO fts_conversation_summaries(fts_conversation_summaries, rowid, summary)
            VALUES ('delete', old.rowid, old.summary);
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_conversation_summaries_au
        AFTER UPDATE ON conversation_summaries
        BEGIN
            INSERT INTO fts_conversation_summaries(fts_conversation_summaries, rowid, summary)
            VALUES ('delete', old.rowid, old.summary);
            INSERT INTO fts_conversation_summaries(rowid, summary)
            VALUES (new.rowid, new.summary);
        END;
        """
    )

    # -----------------------------------------------------------------------
    # 4. Triggers — memory_entries (only index active entries)
    # -----------------------------------------------------------------------

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_memory_entries_ai
        AFTER INSERT ON memory_entries
        WHEN new.archived_at IS NULL AND new.valid_until IS NULL
        BEGIN
            INSERT INTO fts_memory_entries(rowid, value)
            VALUES (new.rowid, new.value);
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_memory_entries_bd
        BEFORE DELETE ON memory_entries
        BEGIN
            INSERT INTO fts_memory_entries(fts_memory_entries, rowid, value)
            VALUES ('delete', old.rowid, old.value);
        END;
        """
    )

    # AFTER UPDATE: remove old entry, re-insert only if still active
    op.execute(
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
        """
    )

    # -----------------------------------------------------------------------
    # 5. Triggers — documents
    # -----------------------------------------------------------------------

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_documents_ai
        AFTER INSERT ON documents
        BEGIN
            INSERT INTO fts_documents(rowid, title, content_text)
            VALUES (new.rowid, new.title, COALESCE(new.content_text, ''));
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_documents_bd
        BEFORE DELETE ON documents
        BEGIN
            INSERT INTO fts_documents(fts_documents, rowid, title, content_text)
            VALUES ('delete', old.rowid, old.title, COALESCE(old.content_text, ''));
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_documents_au
        AFTER UPDATE ON documents
        BEGIN
            INSERT INTO fts_documents(fts_documents, rowid, title, content_text)
            VALUES ('delete', old.rowid, old.title, COALESCE(old.content_text, ''));
            INSERT INTO fts_documents(rowid, title, content_text)
            VALUES (new.rowid, new.title, COALESCE(new.content_text, ''));
        END;
        """
    )


def downgrade() -> None:
    # Drop triggers first, then virtual tables
    for name in [
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
    ]:
        op.execute(f"DROP TRIGGER IF EXISTS {name};")

    for table in [
        "fts_conversation_messages",
        "fts_conversation_summaries",
        "fts_memory_entries",
        "fts_documents",
    ]:
        op.execute(f"DROP TABLE IF EXISTS {table};")
