"""merge 8.2 and 8.3 heads

Revision ID: 6f8f79f85e69
Revises: 3581efe46c8e, 8_3_rule_origin
Create Date: 2026-04-03 11:45:14.929412

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6f8f79f85e69'
down_revision: Union[str, None] = ('3581efe46c8e', '8_3_rule_origin')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
