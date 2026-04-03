"""Fix is_done column on items and FK cascade mismatches

Bug 1.5: The is_done column was never explicitly added to the items table.
The initial migration omitted it, and the 4c1 migration incorrectly assumed
it was already present. It only exists by accident via batch-mode table
recreation picking up the ORM metadata.

Bug 1.6: The initial migration created all FK constraints without ondelete
clauses, but the ORM models define CASCADE or SET NULL. Tests pass because
create_all() uses model definitions, but production migrations have no cascades.

This migration explicitly adds is_done (if missing) and recreates all FK
constraints with the correct ondelete clauses using batch mode.

Revision ID: a1b2c3d4e5f6
Revises: 6_0_automation_service
Create Date: 2026-04-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "6_0_automation_service"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Naming convention used to give predictable names to unnamed reflected FKs.
# Alembic batch mode needs constraint names to drop/recreate them. SQLite
# FKs from the initial migration are unnamed; this convention lets batch
# mode identify them during reflection.
_NAMING_CONVENTION = {
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
}


def upgrade() -> None:
    # SQLite batch mode recreates tables, which fails with FKs enabled.
    op.execute("PRAGMA foreign_keys=OFF")

    conn = op.get_bind()

    # ------------------------------------------------------------------
    # Bug 1.5: Explicitly add is_done to items if it doesn't exist
    # ------------------------------------------------------------------
    inspector = sa_inspect(conn)
    items_columns = [col["name"] for col in inspector.get_columns("items")]
    if "is_done" not in items_columns:
        with op.batch_alter_table("items", schema=None,
                                  naming_convention=_NAMING_CONVENTION) as batch_op:
            batch_op.add_column(
                sa.Column(
                    "is_done",
                    sa.Boolean(),
                    nullable=False,
                    server_default="0",
                ),
            )

    # ------------------------------------------------------------------
    # Bug 1.6: Fix FK cascades on all tables
    # ------------------------------------------------------------------
    # For each table we use batch_alter_table with naming_convention to
    # drop the old FK and create a new one with the correct ondelete.
    # SQLite doesn't support ALTER CONSTRAINT, so batch mode (which
    # recreates the table) is required.
    #
    # Constraint names follow two patterns:
    # - Unnamed FKs (from initial migration): named by convention as
    #   fk_{table}_{column}_{referred_table}
    # - Named FKs (from later migrations): keep their original name
    #   e.g. fk_parent_task_id, fk_consolidated_into

    # -- spaces: parent_space_id -> spaces.id SET NULL --
    with op.batch_alter_table("spaces", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_spaces_parent_space_id_spaces", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_spaces_parent_space_id_spaces",
            "spaces",
            ["parent_space_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # -- agent_permissions: agent_id -> agents.id CASCADE --
    with op.batch_alter_table("agent_permissions", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_agent_permissions_agent_id_agents", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_agent_permissions_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- agent_spaces: both FKs -> CASCADE --
    with op.batch_alter_table("agent_spaces", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_agent_spaces_agent_id_agents", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_agent_spaces_space_id_spaces", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_agent_spaces_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_agent_spaces_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- conversations: space_id -> CASCADE, agent_id -> CASCADE --
    with op.batch_alter_table("conversations", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_conversations_space_id_spaces", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_conversations_agent_id_agents", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_conversations_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_conversations_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- conversation_messages: conversation_id -> CASCADE --
    with op.batch_alter_table("conversation_messages", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_conversation_messages_conversation_id_conversations",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_conversation_messages_conversation_id_conversations",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- conversation_summaries: conversation_id -> CASCADE,
    #    space_id -> CASCADE, consolidated_into -> SET NULL --
    with op.batch_alter_table("conversation_summaries", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_conversation_summaries_conversation_id_conversations",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_conversation_summaries_space_id_spaces", type_="foreignkey"
        )
        # consolidated_into was added with an explicit name in a3b1
        batch_op.drop_constraint(
            "fk_consolidated_into", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_conversation_summaries_conversation_id_conversations",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_conversation_summaries_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_consolidated_into",
            "conversation_summaries",
            ["consolidated_into"],
            ["id"],
            ondelete="SET NULL",
        )

    # -- data_sources: space_id -> CASCADE --
    with op.batch_alter_table("data_sources", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_data_sources_space_id_spaces", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_data_sources_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- documents: space_id -> CASCADE --
    with op.batch_alter_table("documents", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_documents_space_id_spaces", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_documents_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- document_items: document_id -> CASCADE, item_id -> CASCADE --
    with op.batch_alter_table("document_items", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_document_items_document_id_documents", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_document_items_item_id_items", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_document_items_document_id_documents",
            "documents",
            ["document_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_document_items_item_id_items",
            "items",
            ["item_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- items: space_id -> CASCADE, parent_item_id -> SET NULL,
    #    assigned_agent_id -> SET NULL, source_conversation_id -> SET NULL --
    with op.batch_alter_table("items", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_items_space_id_spaces", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_items_parent_item_id_items", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_items_assigned_agent_id_agents", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_items_source_conversation_id_conversations",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_items_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_items_parent_item_id_items",
            "items",
            ["parent_item_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_items_assigned_agent_id_agents",
            "agents",
            ["assigned_agent_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_items_source_conversation_id_conversations",
            "conversations",
            ["source_conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # -- item_events: item_id -> CASCADE --
    with op.batch_alter_table("item_events", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_item_events_item_id_items", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_item_events_item_id_items",
            "items",
            ["item_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- notifications: space_id -> CASCADE, conversation_id -> CASCADE
    #    (automation_id already has ON DELETE SET NULL from 6_0 migration) --
    with op.batch_alter_table("notifications", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_notifications_space_id_spaces", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_notifications_conversation_id_conversations",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_notifications_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_notifications_conversation_id_conversations",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- permission_requests: agent_id -> CASCADE,
    #    conversation_id -> CASCADE --
    with op.batch_alter_table("permission_requests", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_permission_requests_agent_id_agents", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_permission_requests_conversation_id_conversations",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_permission_requests_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_permission_requests_conversation_id_conversations",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- automations: space_id -> SET NULL, agent_id -> CASCADE --
    with op.batch_alter_table("automations", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_automations_space_id_spaces", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_automations_agent_id_agents", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_automations_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_automations_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )

    # -- automation_runs: automation_id -> CASCADE,
    #    background_task_id -> SET NULL --
    with op.batch_alter_table("automation_runs", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_automation_runs_automation_id_automations", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_automation_runs_background_task_id_background_tasks",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_automation_runs_automation_id_automations",
            "automations",
            ["automation_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_automation_runs_background_task_id_background_tasks",
            "background_tasks",
            ["background_task_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # -- behavioral_rules: agent_id -> CASCADE,
    #    source_conversation_id -> SET NULL --
    with op.batch_alter_table("behavioral_rules", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_behavioral_rules_agent_id_agents", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_behavioral_rules_source_conversation_id_conversations",
            type_="foreignkey",
        )
        batch_op.create_foreign_key(
            "fk_behavioral_rules_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_behavioral_rules_source_conversation_id_conversations",
            "conversations",
            ["source_conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # -- background_tasks: conversation_id -> SET NULL,
    #    automation_id -> SET NULL, agent_id -> CASCADE,
    #    space_id -> SET NULL, item_id -> SET NULL,
    #    parent_task_id -> SET NULL --
    with op.batch_alter_table("background_tasks", schema=None,
                              naming_convention=_NAMING_CONVENTION) as batch_op:
        batch_op.drop_constraint(
            "fk_background_tasks_conversation_id_conversations",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_background_tasks_automation_id_automations",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_background_tasks_agent_id_agents", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_background_tasks_space_id_spaces", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_background_tasks_item_id_items", type_="foreignkey"
        )
        # parent_task_id was added with explicit name in a3b1
        batch_op.drop_constraint(
            "fk_parent_task_id", type_="foreignkey"
        )
        batch_op.create_foreign_key(
            "fk_background_tasks_conversation_id_conversations",
            "conversations",
            ["conversation_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_background_tasks_automation_id_automations",
            "automations",
            ["automation_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_background_tasks_agent_id_agents",
            "agents",
            ["agent_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_foreign_key(
            "fk_background_tasks_space_id_spaces",
            "spaces",
            ["space_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_background_tasks_item_id_items",
            "items",
            ["item_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_background_tasks_parent_task_id_background_tasks",
            "background_tasks",
            ["parent_task_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # Re-enable FK enforcement
    op.execute("PRAGMA foreign_keys=ON")


def downgrade() -> None:
    # Downgrade is not practically useful — the old state was broken.
    # Rolling back would reintroduce the missing cascades bug.
    # However, we provide a stub for Alembic chain integrity.
    raise NotImplementedError(
        "Downgrade would reintroduce FK cascade bugs. "
        "Restore from backup if needed."
    )
