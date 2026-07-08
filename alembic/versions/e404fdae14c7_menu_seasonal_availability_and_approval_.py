"""menu seasonal availability and approval workflow

Revision ID: e404fdae14c7
Revises: 122f2270dfbc
Create Date: 2026-07-08 21:34:32.416502

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e404fdae14c7'
down_revision: Union[str, Sequence[str], None] = '122f2270dfbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('dishes', sa.Column('available_from', sa.Date(), nullable=True))
    op.add_column('dishes', sa.Column('available_until', sa.Date(), nullable=True))
    op.add_column('menus', sa.Column('approved_by', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('menus', 'approved_by')
    op.drop_column('dishes', 'available_until')
    op.drop_column('dishes', 'available_from')
