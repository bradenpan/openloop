"""Phase 4c.1: unified item model

Collapse todos into items table. Add is_done to items, rename parent_record_id
to parent_item_id, create item_links table, backfill board_columns on spaces,
migrate existing todos into items, then drop the todos table.

Revision ID: 4c1_unified_items
Revises: 4b1_widgets
Create Date: 2026-03-31
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4c1_unified_items"
down_revision: str | None = "4b1_widgets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # (a) Add is_done column to items table
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("is_done", sa.Boolean(), server_default="0", nullable=False),
        )

    # (b) Rename parent_record_id -> parent_item_id on items table
    #     SQLite batch mode recreates the entire table; the existing FK
    #     constraint is carried over automatically with the renamed column.
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.alter_column("parent_record_id", new_column_name="parent_item_id")

    # (c) Create item_links table
    op.create_table(
        "item_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_item_id",
            sa.String(36),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "target_item_id",
            sa.String(36),
            sa.ForeignKey("items.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("link_type", sa.String(), server_default="related_to"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.UniqueConstraint(
            "source_item_id", "target_item_id", "link_type", name="uq_item_link"
        ),
    )

    # (d) Backfill board_columns on spaces that have NULL
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE spaces SET board_columns = :cols WHERE board_columns IS NULL"
        ),
        {"cols": '["todo", "in_progress", "done"]'},
    )

    # (e) Migrate existing todos into items
    todos = conn.execute(
        sa.text(
            "SELECT id, space_id, title, is_done, due_date, sort_position, "
            "created_by, source_conversation_id, record_id, created_at, updated_at "
            "FROM todos"
        )
    ).fetchall()

    # Build a cache of space_id -> first board column (for stage assignment)
    spaces = conn.execute(
        sa.text("SELECT id, board_columns FROM spaces")
    ).fetchall()
    space_first_col: dict[str, str] = {}
    for space_id, board_columns_raw in spaces:
        if board_columns_raw:
            try:
                cols = json.loads(board_columns_raw) if isinstance(board_columns_raw, str) else board_columns_raw
                if cols and len(cols) > 0:
                    space_first_col[space_id] = cols[0]
            except (json.JSONDecodeError, TypeError):
                space_first_col[space_id] = "todo"
        else:
            space_first_col[space_id] = "todo"

    # Track old todo id -> new item id for link creation in step (f)
    todo_to_item: dict[str, str] = {}

    for todo in todos:
        new_id = str(uuid.uuid4())
        todo_id = todo[0]
        space_id = todo[1]
        title = todo[2]
        is_done = todo[3]
        due_date = todo[4]
        sort_position = todo[5]
        created_by = todo[6]
        source_conversation_id = todo[7]
        record_id = todo[8]
        created_at = todo[9]
        updated_at = todo[10]

        # Determine stage
        if is_done:
            stage = "done"
        else:
            stage = space_first_col.get(space_id, "todo")

        todo_to_item[todo_id] = new_id

        conn.execute(
            sa.text(
                "INSERT INTO items "
                "(id, space_id, item_type, is_agent_task, title, description, stage, "
                "priority, sort_position, custom_fields, parent_item_id, assigned_agent_id, "
                "due_date, created_by, source_conversation_id, archived, is_done, "
                "created_at, updated_at) "
                "VALUES "
                "(:id, :space_id, 'task', 0, :title, NULL, :stage, "
                "NULL, :sort_position, NULL, NULL, NULL, "
                ":due_date, :created_by, :source_conversation_id, 0, :is_done, "
                ":created_at, :updated_at)"
            ),
            {
                "id": new_id,
                "space_id": space_id,
                "title": title,
                "stage": stage,
                "sort_position": sort_position,
                "due_date": due_date,
                "created_by": created_by,
                "source_conversation_id": source_conversation_id,
                "is_done": 1 if is_done else 0,
                "created_at": created_at,
                "updated_at": updated_at,
            },
        )

    # (f) Create item_links for todos that had a record_id
    for todo in todos:
        todo_id = todo[0]
        record_id = todo[8]
        if record_id:
            new_item_id = todo_to_item[todo_id]
            link_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    "INSERT INTO item_links (id, source_item_id, target_item_id, link_type, created_at) "
                    "VALUES (:id, :source, :target, 'related_to', CURRENT_TIMESTAMP)"
                ),
                {
                    "id": link_id,
                    "source": new_item_id,
                    "target": record_id,
                },
            )

    # (g) Drop the todos table
    op.drop_table("todos")


def downgrade() -> None:
    # Drop item_links table
    op.drop_table("item_links")

    # Remove is_done from items
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.drop_column("is_done")

    # Rename parent_item_id back to parent_record_id
    with op.batch_alter_table("items", schema=None) as batch_op:
        batch_op.alter_column("parent_item_id", new_column_name="parent_record_id")

    # Cannot restore todos table — data migration is one-way
    # Recreating an empty todos table would serve no purpose
    raise NotImplementedError(
        "Downgrade cannot restore todos table or migrated data. "
        "Restore from backup if needed."
    )
