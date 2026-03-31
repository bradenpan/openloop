"""add cascades and timestamps

Revision ID: 18110f20765f
Revises: f94010dbad8e
Create Date: 2026-03-30 20:39:29.014141

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "18110f20765f"
down_revision: str | None = "f94010dbad8e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_default_ts = sa.text("(strftime('%Y-%m-%dT%H:%M:%f','now'))")


def upgrade() -> None:
    with op.batch_alter_table("agent_permissions", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_default_ts),
        )

    with op.batch_alter_table("background_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_default_ts),
        )
        batch_op.add_column(
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_default_ts),
        )


def downgrade() -> None:
    with op.batch_alter_table("background_tasks", schema=None) as batch_op:
        batch_op.drop_column("updated_at")
        batch_op.drop_column("created_at")

    with op.batch_alter_table("agent_permissions", schema=None) as batch_op:
        batch_op.drop_column("created_at")
