"""cross-branch stock transfers

Revision ID: 28a9524d6396
Revises: acb6c3845100
Create Date: 2026-07-07 20:43:40.709760

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '28a9524d6396'
down_revision: Union[str, Sequence[str], None] = 'acb6c3845100'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stock_transfers',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('organization_id', sa.BigInteger(), nullable=False),
        sa.Column('from_restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('to_restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['from_restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['to_restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_stock_transfers_from_restaurant_id'), 'stock_transfers', ['from_restaurant_id'], unique=False)
    op.create_index(op.f('ix_stock_transfers_organization_id'), 'stock_transfers', ['organization_id'], unique=False)
    op.create_index(op.f('ix_stock_transfers_status'), 'stock_transfers', ['status'], unique=False)
    op.create_index(op.f('ix_stock_transfers_to_restaurant_id'), 'stock_transfers', ['to_restaurant_id'], unique=False)

    op.create_table(
        'stock_transfer_lines',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('transfer_id', sa.BigInteger(), nullable=False),
        sa.Column('ingredient_name', sa.String(length=128), nullable=False),
        sa.Column('unit', sa.String(length=16), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['transfer_id'], ['stock_transfers.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_stock_transfer_lines_transfer_id'), 'stock_transfer_lines', ['transfer_id'], unique=False)

    op.execute(
        "CREATE TRIGGER trg_stock_transfers_updated_at BEFORE UPDATE ON stock_transfers "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )
    op.execute(
        "CREATE TRIGGER trg_stock_transfer_lines_updated_at BEFORE UPDATE ON stock_transfer_lines "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_stock_transfer_lines_updated_at ON stock_transfer_lines;")
    op.execute("DROP TRIGGER IF EXISTS trg_stock_transfers_updated_at ON stock_transfers;")

    op.drop_index(op.f('ix_stock_transfer_lines_transfer_id'), table_name='stock_transfer_lines')
    op.drop_table('stock_transfer_lines')

    op.drop_index(op.f('ix_stock_transfers_to_restaurant_id'), table_name='stock_transfers')
    op.drop_index(op.f('ix_stock_transfers_status'), table_name='stock_transfers')
    op.drop_index(op.f('ix_stock_transfers_organization_id'), table_name='stock_transfers')
    op.drop_index(op.f('ix_stock_transfers_from_restaurant_id'), table_name='stock_transfers')
    op.drop_table('stock_transfers')
