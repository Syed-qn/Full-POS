"""vendors, purchase orders, stock counts, ingredient batches

Revision ID: 03b3d42e1ef8
Revises: 9be09f780ce3
Create Date: 2026-07-07 20:53:28.802771

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '03b3d42e1ef8'
down_revision: Union[str, Sequence[str], None] = '935866c7d327'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'vendors',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('phone', sa.String(length=32), nullable=True),
        sa.Column('email', sa.String(length=128), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_vendors_restaurant_id'), 'vendors', ['restaurant_id'], unique=False)

    op.create_table(
        'purchase_orders',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('vendor_id', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['vendor_id'], ['vendors.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_purchase_orders_restaurant_id'), 'purchase_orders', ['restaurant_id'], unique=False)
    op.create_index(op.f('ix_purchase_orders_vendor_id'), 'purchase_orders', ['vendor_id'], unique=False)

    op.create_table(
        'purchase_order_lines',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('po_id', sa.BigInteger(), nullable=False),
        sa.Column('ingredient_id', sa.BigInteger(), nullable=False),
        sa.Column('qty_ordered', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column('unit_cost_aed', sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id']),
        sa.ForeignKeyConstraint(['po_id'], ['purchase_orders.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_purchase_order_lines_ingredient_id'), 'purchase_order_lines', ['ingredient_id'], unique=False)
    op.create_index(op.f('ix_purchase_order_lines_po_id'), 'purchase_order_lines', ['po_id'], unique=False)

    op.create_table(
        'ingredient_batches',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('ingredient_id', sa.BigInteger(), nullable=False),
        sa.Column('qty', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column('expiry_date', sa.Date(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id']),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ingredient_batches_ingredient_id'), 'ingredient_batches', ['ingredient_id'], unique=False)
    op.create_index(op.f('ix_ingredient_batches_restaurant_id'), 'ingredient_batches', ['restaurant_id'], unique=False)

    for tbl in ('vendors', 'purchase_orders', 'purchase_order_lines', 'ingredient_batches'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ('vendors', 'purchase_orders', 'purchase_order_lines', 'ingredient_batches'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")

    op.drop_index(op.f('ix_ingredient_batches_restaurant_id'), table_name='ingredient_batches')
    op.drop_index(op.f('ix_ingredient_batches_ingredient_id'), table_name='ingredient_batches')
    op.drop_table('ingredient_batches')

    op.drop_index(op.f('ix_purchase_order_lines_po_id'), table_name='purchase_order_lines')
    op.drop_index(op.f('ix_purchase_order_lines_ingredient_id'), table_name='purchase_order_lines')
    op.drop_table('purchase_order_lines')

    op.drop_index(op.f('ix_purchase_orders_vendor_id'), table_name='purchase_orders')
    op.drop_index(op.f('ix_purchase_orders_restaurant_id'), table_name='purchase_orders')
    op.drop_table('purchase_orders')

    op.drop_index(op.f('ix_vendors_restaurant_id'), table_name='vendors')
    op.drop_table('vendors')
