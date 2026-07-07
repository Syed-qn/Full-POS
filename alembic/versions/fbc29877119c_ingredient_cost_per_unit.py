"""ingredient cost per unit

Revision ID: fbc29877119c
Revises: e65a577f953d
Create Date: 2026-07-07 17:16:27.185548

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fbc29877119c'
down_revision: Union[str, Sequence[str], None] = 'e65a577f953d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ingredients',
        sa.Column('cost_per_unit_aed', sa.Numeric(precision=10, scale=4), nullable=False, server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('ingredients', 'cost_per_unit_aed')
