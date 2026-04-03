"""Phase 8.6a: Compaction loop — add goal and time_budget to background_tasks

Add goal (Text, nullable) for storing the original instruction/goal used in
compaction verification.
Add time_budget (Integer, nullable) for max wall-clock seconds.

Revision ID: 8_6a_compaction
Revises: 73a95abf891f
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8_6a_compaction"
down_revision: str | None = "73a95abf891f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("background_tasks", sa.Column("goal", sa.Text(), nullable=True))
    op.add_column("background_tasks", sa.Column("time_budget", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("background_tasks", "time_budget")
    op.drop_column("background_tasks", "goal")
