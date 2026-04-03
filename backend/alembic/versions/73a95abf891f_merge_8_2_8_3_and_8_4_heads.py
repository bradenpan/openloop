"""merge 8.2-8.3 and 8.4 heads

Revision ID: 73a95abf891f
Revises: 6f8f79f85e69, 8_4_kill_switch
Create Date: 2026-04-03 11:45:33.941763

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73a95abf891f'
down_revision: Union[str, None] = ('6f8f79f85e69', '8_4_kill_switch')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
