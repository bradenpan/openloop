"""Add indexes on frequently-queried columns

Index notifications.created_at, conversation_messages.created_at,
items.stage, and background_tasks.status for query performance.

Revision ID: 7_4_query_indexes
Revises: a1b2c3d4e5f6
Create Date: 2026-04-02
"""

from collections.abc import Sequence

from alembic import op

revision: str = "7_4_query_indexes"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_notifications_created_at", "notifications", ["created_at"])
    op.create_index("ix_conversation_messages_created_at", "conversation_messages", ["created_at"])
    op.create_index("ix_items_stage", "items", ["stage"])
    op.create_index("ix_background_tasks_status", "background_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_background_tasks_status", table_name="background_tasks")
    op.drop_index("ix_items_stage", table_name="items")
    op.drop_index("ix_conversation_messages_created_at", table_name="conversation_messages")
    op.drop_index("ix_notifications_created_at", table_name="notifications")
