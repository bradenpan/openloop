"""Phase 9.1: Schema extensions for autonomous agent operations

Add to background_tasks: task_list, task_list_version, completed_count,
total_count, queued_approvals_count, run_type, run_summary.

Add to agents: max_spawn_depth, heartbeat_enabled, heartbeat_cron.

Create approval_queue table.

Revision ID: 9_1_autonomous
Revises: 8_6a_compaction
Create Date: 2026-04-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9_1_autonomous"
down_revision: str | None = "8_6a_compaction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # -- background_tasks: new columns --
    op.add_column("background_tasks", sa.Column("task_list", sa.JSON(), nullable=True))
    op.add_column(
        "background_tasks",
        sa.Column("task_list_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "background_tasks",
        sa.Column("completed_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "background_tasks",
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "background_tasks",
        sa.Column("queued_approvals_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "background_tasks",
        sa.Column("run_type", sa.String(), nullable=False, server_default="task"),
    )
    op.add_column("background_tasks", sa.Column("run_summary", sa.Text(), nullable=True))

    # -- agents: new columns --
    op.add_column(
        "agents",
        sa.Column("max_spawn_depth", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "agents",
        sa.Column("heartbeat_enabled", sa.Boolean(), nullable=False, server_default="0"),
    )
    op.add_column("agents", sa.Column("heartbeat_cron", sa.String(), nullable=True))

    # -- approval_queue: new table --
    op.create_table(
        "approval_queue",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "background_task_id",
            sa.String(36),
            sa.ForeignKey("background_tasks.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "agent_id",
            sa.String(36),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("action_detail", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("approval_queue")

    op.drop_column("agents", "heartbeat_cron")
    op.drop_column("agents", "heartbeat_enabled")
    op.drop_column("agents", "max_spawn_depth")

    op.drop_column("background_tasks", "run_summary")
    op.drop_column("background_tasks", "run_type")
    op.drop_column("background_tasks", "queued_approvals_count")
    op.drop_column("background_tasks", "total_count")
    op.drop_column("background_tasks", "completed_count")
    op.drop_column("background_tasks", "task_list_version")
    op.drop_column("background_tasks", "task_list")
