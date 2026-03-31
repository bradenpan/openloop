"""Phase 4.1: records backend

Add custom_field_schema to spaces table.
Add record_id to todos table for linking todos to records.

Revision ID: b4c2_records
Revises: a3b1_memory_arch
Create Date: 2026-03-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4c2_records"
down_revision: str | None = "a3b1_memory_arch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- spaces: custom field schema for CRM-style records --
    with op.batch_alter_table("spaces", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("custom_field_schema", sa.JSON(), nullable=True),
        )

    # -- todos: link to a record item --
    with op.batch_alter_table("todos", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "record_id",
                sa.String(36),
                sa.ForeignKey("items.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("todos", schema=None) as batch_op:
        batch_op.drop_column("record_id")

    with op.batch_alter_table("spaces", schema=None) as batch_op:
        batch_op.drop_column("custom_field_schema")
