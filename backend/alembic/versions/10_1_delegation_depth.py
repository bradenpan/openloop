"""Phase 10.1: Add delegation_depth to background_tasks

Supports permission narrowing for multi-agent delegation.

Revision ID: 10_1_delegation_depth
Revises: 9_1_autonomous
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "10_1_delegation_depth"
down_revision: str | None = "9_1_autonomous"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("background_tasks") as batch_op:
        batch_op.add_column(
            sa.Column("delegation_depth", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    with op.batch_alter_table("background_tasks") as batch_op:
        batch_op.drop_column("delegation_depth")
