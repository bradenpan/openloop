"""Phase 12-14: Integration infrastructure

- ALTER data_sources.space_id to nullable (system-level data sources)
- ADD is_system column to automations (Boolean, default False)
- CREATE space_data_source_exclusions join table
- CREATE calendar_events table (Google Calendar cache)
- CREATE email_cache table (Gmail cache)
- CREATE FTS5 virtual tables + triggers for calendar_events and email_cache

Revision ID: 12_1_integration
Revises: 10_2_fts_items
Create Date: 2026-04-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "12_1_integration"
down_revision: str | None = "10_2_fts_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Make data_sources.space_id nullable
    # ------------------------------------------------------------------
    with op.batch_alter_table("data_sources") as batch_op:
        batch_op.alter_column(
            "space_id",
            existing_type=sa.String(36),
            nullable=True,
        )

    # ------------------------------------------------------------------
    # 2. Add is_system column to automations
    # ------------------------------------------------------------------
    with op.batch_alter_table("automations") as batch_op:
        batch_op.add_column(
            sa.Column("is_system", sa.Boolean(), nullable=False, server_default="0"),
        )

    # ------------------------------------------------------------------
    # 3. Create space_data_source_exclusions join table
    # ------------------------------------------------------------------
    op.create_table(
        "space_data_source_exclusions",
        sa.Column("space_id", sa.String(36), sa.ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), primary_key=True),
    )

    # ------------------------------------------------------------------
    # 4. Create calendar_events table
    # ------------------------------------------------------------------
    op.create_table(
        "calendar_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("google_event_id", sa.String(), unique=True, nullable=True),
        sa.Column("calendar_id", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("end_time", sa.DateTime(), nullable=False),
        sa.Column("all_day", sa.Boolean(), server_default="0"),
        sa.Column("attendees", sa.JSON(), nullable=True),
        sa.Column("organizer", sa.JSON(), nullable=True),
        sa.Column("conference_data", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(), server_default="confirmed"),
        sa.Column("recurrence_rule", sa.String(), nullable=True),
        sa.Column("html_link", sa.String(), nullable=True),
        sa.Column("etag", sa.String(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # ------------------------------------------------------------------
    # 5. Create email_cache table
    # ------------------------------------------------------------------
    op.create_table(
        "email_cache",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("gmail_message_id", sa.String(), unique=True, nullable=True),
        sa.Column("gmail_thread_id", sa.String(), nullable=True),
        sa.Column("subject", sa.String(), nullable=True),
        sa.Column("from_address", sa.String(), nullable=True),
        sa.Column("from_name", sa.String(), nullable=True),
        sa.Column("to_addresses", sa.JSON(), nullable=True),
        sa.Column("cc_addresses", sa.JSON(), nullable=True),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=True),
        sa.Column("is_unread", sa.Boolean(), server_default="1"),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("gmail_link", sa.String(), nullable=True),
        sa.Column("synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # ------------------------------------------------------------------
    # 6. FTS5 virtual tables + triggers — calendar_events
    # ------------------------------------------------------------------
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_calendar_events
        USING fts5(title, description, content='calendar_events', content_rowid='rowid');
    """)

    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_calendar_events_ai
        AFTER INSERT ON calendar_events
        BEGIN
            INSERT INTO fts_calendar_events(rowid, title, description)
            VALUES (new.rowid, new.title, COALESCE(new.description, ''));
        END;
    """)

    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_calendar_events_bd
        BEFORE DELETE ON calendar_events
        BEGIN
            INSERT INTO fts_calendar_events(fts_calendar_events, rowid, title, description)
            VALUES ('delete', old.rowid, old.title, COALESCE(old.description, ''));
        END;
    """)

    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_calendar_events_au
        AFTER UPDATE ON calendar_events
        BEGIN
            INSERT INTO fts_calendar_events(fts_calendar_events, rowid, title, description)
            VALUES ('delete', old.rowid, old.title, COALESCE(old.description, ''));
            INSERT INTO fts_calendar_events(rowid, title, description)
            VALUES (new.rowid, new.title, COALESCE(new.description, ''));
        END;
    """)

    # ------------------------------------------------------------------
    # 7. FTS5 virtual tables + triggers — email_cache
    # ------------------------------------------------------------------
    op.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS fts_email_cache
        USING fts5(subject, from_name, snippet, content='email_cache', content_rowid='rowid');
    """)

    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_email_cache_ai
        AFTER INSERT ON email_cache
        BEGIN
            INSERT INTO fts_email_cache(rowid, subject, from_name, snippet)
            VALUES (new.rowid, COALESCE(new.subject, ''), COALESCE(new.from_name, ''), COALESCE(new.snippet, ''));
        END;
    """)

    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_email_cache_bd
        BEFORE DELETE ON email_cache
        BEGIN
            INSERT INTO fts_email_cache(fts_email_cache, rowid, subject, from_name, snippet)
            VALUES ('delete', old.rowid, COALESCE(old.subject, ''), COALESCE(old.from_name, ''), COALESCE(old.snippet, ''));
        END;
    """)

    op.execute("""
        CREATE TRIGGER IF NOT EXISTS fts_email_cache_au
        AFTER UPDATE ON email_cache
        BEGIN
            INSERT INTO fts_email_cache(fts_email_cache, rowid, subject, from_name, snippet)
            VALUES ('delete', old.rowid, COALESCE(old.subject, ''), COALESCE(old.from_name, ''), COALESCE(old.snippet, ''));
            INSERT INTO fts_email_cache(rowid, subject, from_name, snippet)
            VALUES (new.rowid, COALESCE(new.subject, ''), COALESCE(new.from_name, ''), COALESCE(new.snippet, ''));
        END;
    """)


def downgrade() -> None:
    # Drop FTS triggers
    for name in [
        "fts_calendar_events_ai",
        "fts_calendar_events_bd",
        "fts_calendar_events_au",
        "fts_email_cache_ai",
        "fts_email_cache_bd",
        "fts_email_cache_au",
    ]:
        op.execute(f"DROP TRIGGER IF EXISTS {name};")

    # Drop FTS virtual tables
    for table in ["fts_calendar_events", "fts_email_cache"]:
        op.execute(f"DROP TABLE IF EXISTS {table};")

    # Drop new tables
    op.drop_table("email_cache")
    op.drop_table("calendar_events")
    op.drop_table("space_data_source_exclusions")

    # Remove is_system from automations
    with op.batch_alter_table("automations") as batch_op:
        batch_op.drop_column("is_system")

    # Revert data_sources.space_id to non-nullable
    with op.batch_alter_table("data_sources") as batch_op:
        batch_op.alter_column(
            "space_id",
            existing_type=sa.String(36),
            nullable=False,
        )
