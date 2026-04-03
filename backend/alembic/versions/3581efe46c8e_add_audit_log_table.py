"""add audit_log table

Revision ID: 3581efe46c8e
Revises: 7_4_query_indexes
Create Date: 2026-04-03 11:42:34.531727

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '3581efe46c8e'
down_revision: Union[str, None] = '7_4_query_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('agent_id', sa.String(length=36), nullable=False),
    sa.Column('conversation_id', sa.String(length=36), nullable=True),
    sa.Column('background_task_id', sa.String(length=36), nullable=True),
    sa.Column('tool_name', sa.String(), nullable=False),
    sa.Column('action', sa.String(), nullable=False),
    sa.Column('resource_id', sa.String(), nullable=True),
    sa.Column('input_summary', sa.Text(), nullable=True),
    sa.Column('timestamp', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['background_task_id'], ['background_tasks.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_conversation_id'), ['conversation_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_timestamp'), ['timestamp'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_timestamp'))
        batch_op.drop_index(batch_op.f('ix_audit_log_conversation_id'))
        batch_op.drop_index(batch_op.f('ix_audit_log_agent_id'))

    op.drop_table('audit_log')
