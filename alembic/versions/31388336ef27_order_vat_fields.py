"""order vat fields

Revision ID: 31388336ef27
Revises: 86a678ed9b4d
Create Date: 2026-07-07 09:12:15.596936

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '31388336ef27'
down_revision: Union[str, Sequence[str], None] = '86a678ed9b4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'orders', sa.Column('vat_rate', sa.Numeric(precision=5, scale=4), nullable=False, server_default='0.05')
    )
    op.add_column(
        'orders', sa.Column('vat_amount_aed', sa.Numeric(precision=8, scale=2), nullable=False, server_default='0')
    )


def downgrade() -> None:
    op.drop_column('orders', 'vat_amount_aed')
    op.drop_column('orders', 'vat_rate')
