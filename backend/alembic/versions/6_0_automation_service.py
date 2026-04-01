"""Phase 6.0: add automation_id FK to notifications

The automations and automation_runs tables already exist (created in initial schema).
This migration only adds the automation_id nullable FK column to the notifications table.
"""

import sqlalchemy as sa  # noqa: E402

from alembic import op

revision: str = "6_0_automation_service"
down_revision: str | None = "5_0_skill_path"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.add_column(sa.Column("automation_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_notifications_automation_id",
            "automations",
            ["automation_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("notifications", schema=None) as batch_op:
        batch_op.drop_constraint("fk_notifications_automation_id", type_="foreignkey")
        batch_op.drop_column("automation_id")
