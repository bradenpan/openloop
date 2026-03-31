"""Phase 3b: memory architecture upgrade

Add scored retrieval, temporal facts, and lifecycle fields to memory_entries.
Add summary consolidation fields to conversation_summaries.
Add workflow tracking fields to background_tasks.
Create behavioral_rules table for procedural memory.

Revision ID: a3b1_memory_arch
Revises: 18110f20765f
Create Date: 2026-03-31
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3b1_memory_arch"
down_revision: str | None = "18110f20765f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_default_ts = sa.text("(strftime('%Y-%m-%dT%H:%M:%f','now'))")


def upgrade() -> None:
    # -- memory_entries: scored retrieval + temporal facts + lifecycle --
    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("importance", sa.Float(), nullable=False, server_default="0.5"),
        )
        batch_op.add_column(
            sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column("last_accessed", sa.DateTime(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("valid_from", sa.DateTime(), nullable=False, server_default=_default_ts),
        )
        batch_op.add_column(
            sa.Column("valid_until", sa.DateTime(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("archived_at", sa.DateTime(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("category", sa.String(), nullable=True),
        )

    # -- conversation_summaries: consolidation support --
    with op.batch_alter_table("conversation_summaries", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_meta_summary", sa.Boolean(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column("consolidated_into", sa.String(36), nullable=True),
        )
        batch_op.create_foreign_key(
            "fk_consolidated_into",
            "conversation_summaries",
            ["consolidated_into"],
            ["id"],
        )

    # -- background_tasks: workflow tracking --
    with op.batch_alter_table("background_tasks", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("current_step", sa.Integer(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("total_steps", sa.Integer(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("step_results", sa.JSON(), nullable=True),
        )
        batch_op.add_column(
            sa.Column("parent_task_id", sa.String(36), nullable=True),
        )
        batch_op.create_foreign_key(
            "fk_parent_task_id",
            "background_tasks",
            ["parent_task_id"],
            ["id"],
        )

    # -- behavioral_rules: procedural memory --
    op.create_table(
        "behavioral_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("rule", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column(
            "source_conversation_id",
            sa.String(36),
            sa.ForeignKey("conversations.id"),
            nullable=True,
        ),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("apply_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_applied", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=_default_ts),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=_default_ts),
    )
    op.create_index("ix_behavioral_rules_agent_id", "behavioral_rules", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_behavioral_rules_agent_id")
    op.drop_table("behavioral_rules")

    with op.batch_alter_table("background_tasks", schema=None) as batch_op:
        batch_op.drop_column("parent_task_id")
        batch_op.drop_column("step_results")
        batch_op.drop_column("total_steps")
        batch_op.drop_column("current_step")

    with op.batch_alter_table("conversation_summaries", schema=None) as batch_op:
        batch_op.drop_column("consolidated_into")
        batch_op.drop_column("is_meta_summary")

    with op.batch_alter_table("memory_entries", schema=None) as batch_op:
        batch_op.drop_column("category")
        batch_op.drop_column("archived_at")
        batch_op.drop_column("valid_until")
        batch_op.drop_column("valid_from")
        batch_op.drop_column("last_accessed")
        batch_op.drop_column("access_count")
        batch_op.drop_column("importance")
