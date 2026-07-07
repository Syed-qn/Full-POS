"""payment transactions

Revision ID: 823a3cfe717b
Revises: 05fede78a55e
Create Date: 2026-07-07 11:12:14.314113

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '823a3cfe717b'
down_revision: Union[str, Sequence[str], None] = '05fede78a55e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'payment_transactions',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('tender_type', sa.String(length=16), nullable=False),
        sa.Column('amount_aed', sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column('tip_aed', sa.Numeric(precision=8, scale=2), nullable=False, server_default='0'),
        sa.Column('provider', sa.String(length=16), nullable=False, server_default='mock'),
        sa.Column('provider_charge_id', sa.String(length=128), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False, server_default='pending'),
        sa.Column('refunded_amount_aed', sa.Numeric(precision=8, scale=2), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_payment_transactions_order_id'), 'payment_transactions', ['order_id'], unique=False)
    op.create_index(op.f('ix_payment_transactions_restaurant_id'), 'payment_transactions', ['restaurant_id'], unique=False)

    op.execute(
        "CREATE TRIGGER trg_payment_transactions_updated_at BEFORE UPDATE ON payment_transactions "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_payment_transactions_updated_at ON payment_transactions;")
    op.drop_index(op.f('ix_payment_transactions_restaurant_id'), table_name='payment_transactions')
    op.drop_index(op.f('ix_payment_transactions_order_id'), table_name='payment_transactions')
    op.drop_table('payment_transactions')
