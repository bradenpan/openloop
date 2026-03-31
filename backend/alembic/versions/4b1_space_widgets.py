"""Phase 4b.1: space_widgets table

Add space_widgets table for configurable widget-based space layouts.
Data migration: insert default widgets for all existing spaces based on template.

Revision ID: 4b1_widgets
Revises: fts5_search
Create Date: 2026-03-31
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "4b1_widgets"
down_revision: str | None = "fts5_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Default widgets per template: list of (widget_type, size) tuples
_TEMPLATE_WIDGETS: dict[str, list[tuple[str, str]]] = {
    "project": [
        ("todo_panel", "small"),
        ("kanban_board", "large"),
        ("conversations", "small"),
    ],
    "crm": [
        ("todo_panel", "small"),
        ("data_table", "large"),
        ("conversations", "small"),
    ],
    "knowledge_base": [
        ("conversations", "large"),
    ],
    "simple": [
        ("todo_panel", "large"),
        ("conversations", "medium"),
    ],
}


def upgrade() -> None:
    # -- Create space_widgets table --
    op.create_table(
        "space_widgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("spaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("widget_type", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("size", sa.String(), server_default="medium"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
    )

    # -- Data migration: insert default widgets for existing spaces --
    conn = op.get_bind()
    spaces = conn.execute(sa.text("SELECT id, template FROM spaces")).fetchall()

    for space_id, template in spaces:
        widget_defs = _TEMPLATE_WIDGETS.get(template, _TEMPLATE_WIDGETS["simple"])
        for position, (widget_type, size) in enumerate(widget_defs):
            widget_id = str(uuid.uuid4())
            conn.execute(
                sa.text(
                    "INSERT INTO space_widgets (id, space_id, widget_type, position, size, created_at, updated_at) "
                    "VALUES (:id, :space_id, :widget_type, :position, :size, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "id": widget_id,
                    "space_id": space_id,
                    "widget_type": widget_type,
                    "position": position,
                    "size": size,
                },
            )


def downgrade() -> None:
    op.drop_table("space_widgets")
