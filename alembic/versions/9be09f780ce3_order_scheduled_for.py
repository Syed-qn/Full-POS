"""order scheduled_for

Revision ID: 9be09f780ce3
Revises: 23fe040d7fe8
Create Date: 2026-07-07 18:03:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '9be09f780ce3'
down_revision: Union[str, Sequence[str], None] = '23fe040d7fe8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('scheduled_for', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'scheduled_for')
