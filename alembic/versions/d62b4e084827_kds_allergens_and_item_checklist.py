"""kds allergens and item checklist

Revision ID: d62b4e084827
Revises: 122f2270dfbc
Create Date: 2026-07-07 23:07:32.668539

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd62b4e084827'
down_revision: Union[str, Sequence[str], None] = '122f2270dfbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('dishes', sa.Column('allergens', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('order_items', sa.Column('allergens_snapshot', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('order_items', sa.Column('packaging_checked', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('order_items', sa.Column('quality_checked', sa.Boolean(), server_default='false', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('order_items', 'quality_checked')
    op.drop_column('order_items', 'packaging_checked')
    op.drop_column('order_items', 'allergens_snapshot')
    op.drop_column('dishes', 'allergens')
