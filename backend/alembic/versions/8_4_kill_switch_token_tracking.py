"""Phase 8.4: Kill switch (system_state table) + token tracking columns

New system_state table for key-value system flags.
Add input_tokens, output_tokens to conversation_messages.
Add token_budget to background_tasks.

Revision ID: 8_4_kill_switch
Revises: 7_4_query_indexes
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8_4_kill_switch"
down_revision: str | None = "7_4_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # New system_state table
    op.create_table(
        "system_state",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )

    # Token tracking on conversation_messages
    op.add_column("conversation_messages", sa.Column("input_tokens", sa.Integer(), nullable=True))
    op.add_column("conversation_messages", sa.Column("output_tokens", sa.Integer(), nullable=True))

    # Token budget on background_tasks
    op.add_column("background_tasks", sa.Column("token_budget", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("background_tasks", "token_budget")
    op.drop_column("conversation_messages", "output_tokens")
    op.drop_column("conversation_messages", "input_tokens")
    op.drop_table("system_state")
