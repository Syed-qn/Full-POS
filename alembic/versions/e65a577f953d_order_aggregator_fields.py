"""order aggregator fields

Revision ID: e65a577f953d
Revises: 823a3cfe717b
Create Date: 2026-07-07 11:48:23.027853

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e65a577f953d'
down_revision: Union[str, Sequence[str], None] = '823a3cfe717b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('aggregator_source', sa.String(length=24), nullable=True))
    op.add_column('orders', sa.Column('aggregator_order_ref', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'aggregator_order_ref')
    op.drop_column('orders', 'aggregator_source')
