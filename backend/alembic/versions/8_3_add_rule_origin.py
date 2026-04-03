"""Add origin column to behavioral_rules table

Track whether a behavioral rule was agent-inferred, user-confirmed, or system-defined.
This enables attention-optimized placement: user_confirmed/system rules go in the
high-attention beginning section, agent_inferred rules go in the lower-attention middle.

Revision ID: 8_3_rule_origin
Revises: 7_4_query_indexes
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8_3_rule_origin"
down_revision: str | None = "7_4_query_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "behavioral_rules",
        sa.Column("origin", sa.String(), nullable=False, server_default="agent_inferred"),
    )


def downgrade() -> None:
    op.drop_column("behavioral_rules", "origin")
