"""loyalty referrals and nps

Revision ID: 122f2270dfbc
Revises: 28a9524d6396
Create Date: 2026-07-07 21:25:26.560338

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '122f2270dfbc'
down_revision: Union[str, Sequence[str], None] = '28a9524d6396'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'referral_codes',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('customer_id', sa.BigInteger(), nullable=False),
        sa.Column('code', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id']),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('restaurant_id', 'code', name='uq_referral_codes_restaurant_code'),
    )
    op.create_index(op.f('ix_referral_codes_code'), 'referral_codes', ['code'], unique=False)
    op.create_index(op.f('ix_referral_codes_customer_id'), 'referral_codes', ['customer_id'], unique=False)
    op.create_index(op.f('ix_referral_codes_restaurant_id'), 'referral_codes', ['restaurant_id'], unique=False)

    op.create_table(
        'nps_responses',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('customer_id', sa.BigInteger(), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('score', sa.SmallInteger(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id']),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_nps_responses_customer_id'), 'nps_responses', ['customer_id'], unique=False)
    op.create_index(op.f('ix_nps_responses_order_id'), 'nps_responses', ['order_id'], unique=False)
    op.create_index('ix_nps_responses_restaurant_created_at', 'nps_responses', ['restaurant_id', 'created_at'], unique=False)
    op.create_index(op.f('ix_nps_responses_restaurant_id'), 'nps_responses', ['restaurant_id'], unique=False)

    op.add_column('customers', sa.Column('referred_by_customer_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_customers_referred_by_customer_id', 'customers', 'customers',
        ['referred_by_customer_id'], ['id'],
    )
    # Orphaned column from a reverted experiment (superseded by app.loyalty's
    # tier/cashback system) — finally dropped here.
    op.drop_column('customers', 'loyalty_points')

    for tbl in ('referral_codes', 'nps_responses'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ('referral_codes', 'nps_responses'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")

    op.add_column(
        'customers',
        sa.Column('loyalty_points', sa.Integer(), server_default=sa.text('0'), nullable=False),
    )
    op.drop_constraint('fk_customers_referred_by_customer_id', 'customers', type_='foreignkey')
    op.drop_column('customers', 'referred_by_customer_id')

    op.drop_index(op.f('ix_nps_responses_restaurant_id'), table_name='nps_responses')
    op.drop_index('ix_nps_responses_restaurant_created_at', table_name='nps_responses')
    op.drop_index(op.f('ix_nps_responses_order_id'), table_name='nps_responses')
    op.drop_index(op.f('ix_nps_responses_customer_id'), table_name='nps_responses')
    op.drop_table('nps_responses')

    op.drop_index(op.f('ix_referral_codes_restaurant_id'), table_name='referral_codes')
    op.drop_index(op.f('ix_referral_codes_customer_id'), table_name='referral_codes')
    op.drop_index(op.f('ix_referral_codes_code'), table_name='referral_codes')
    op.drop_table('referral_codes')
