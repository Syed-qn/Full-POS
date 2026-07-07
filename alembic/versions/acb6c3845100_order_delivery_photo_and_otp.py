"""order delivery photo and otp

Revision ID: acb6c3845100
Revises: t1u2v3w4x5y6
Create Date: 2026-07-07 21:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'acb6c3845100'
down_revision: Union[str, Sequence[str], None] = 't1u2v3w4x5y6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('delivery_photo_url', sa.String(length=512), nullable=True))
    op.add_column('orders', sa.Column('delivery_otp', sa.String(length=4), nullable=True))
    op.add_column('orders', sa.Column('delivery_otp_verified_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('orders', 'delivery_otp_verified_at')
    op.drop_column('orders', 'delivery_otp')
    op.drop_column('orders', 'delivery_photo_url')
