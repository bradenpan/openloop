"""Phase 5.0: add skill_path to agents

Add skill_path column to agents table for linking agents to skill definitions
on disk (agents/skills/{name}/SKILL.md). When set, SessionManager loads the
system prompt from the SKILL.md file instead of the system_prompt column.
"""

from alembic import op
import sqlalchemy as sa

revision: str = "5_0_skill_path"
down_revision: str | None = "4c1_unified_items"
branch_labels: tuple | None = None
depends_on: tuple | None = None


def upgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("skill_path", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agents", schema=None) as batch_op:
        batch_op.drop_column("skill_path")
