"""Phase 4.3: add file_size, mime_type, content_text to documents

Revision ID: b4c2_doc_mgmt
Revises: b4c2_records
Create Date: 2026-03-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b4c2_doc_mgmt"
down_revision: str | None = "b4c2_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("file_size", sa.Integer(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("mime_type", sa.String(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("content_text", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    with op.batch_alter_table("documents", schema=None) as batch_op:
        batch_op.drop_column("content_text")
        batch_op.drop_column("mime_type")
        batch_op.drop_column("file_size")
