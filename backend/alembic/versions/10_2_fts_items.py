"""FTS5 index for items table

Create FTS5 virtual table and sync triggers for full-text search
on items (title + description).

Revision ID: 10_2_fts_items
Revises: 10_1_delegation_depth
Create Date: 2026-04-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "10_2_fts_items"
down_revision: str | None = "10_1_delegation_depth"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -----------------------------------------------------------------------
    # 1. FTS5 virtual table (external content)
    # -----------------------------------------------------------------------

    op.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_items
        USING fts5(title, description, content='items', content_rowid='rowid');
        """
    )

    # -----------------------------------------------------------------------
    # 2. Triggers — items
    # -----------------------------------------------------------------------

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_items_ai
        AFTER INSERT ON items
        BEGIN
            INSERT INTO fts_items(rowid, title, description)
            VALUES (new.rowid, new.title, COALESCE(new.description, ''));
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_items_bd
        BEFORE DELETE ON items
        BEGIN
            INSERT INTO fts_items(fts_items, rowid, title, description)
            VALUES ('delete', old.rowid, old.title, COALESCE(old.description, ''));
        END;
        """
    )

    op.execute(
        """
        CREATE TRIGGER IF NOT EXISTS fts_items_au
        AFTER UPDATE ON items
        BEGIN
            INSERT INTO fts_items(fts_items, rowid, title, description)
            VALUES ('delete', old.rowid, old.title, COALESCE(old.description, ''));
            INSERT INTO fts_items(rowid, title, description)
            VALUES (new.rowid, new.title, COALESCE(new.description, ''));
        END;
        """
    )


def downgrade() -> None:
    for name in [
        "fts_items_ai",
        "fts_items_bd",
        "fts_items_au",
    ]:
        op.execute(f"DROP TRIGGER IF EXISTS {name};")

    op.execute("DROP TABLE IF EXISTS fts_items;")
