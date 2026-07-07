"""inventory tables

Revision ID: 5579c35aeaf5
Revises: 851e6ac56e32
Create Date: 2026-07-07 08:52:59.756860

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5579c35aeaf5'
down_revision: Union[str, Sequence[str], None] = '851e6ac56e32'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ingredients',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('unit', sa.String(length=16), nullable=False),
        sa.Column('current_stock', sa.Numeric(precision=10, scale=3), nullable=False, server_default='0'),
        sa.Column('low_stock_threshold', sa.Numeric(precision=10, scale=3), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_ingredients_restaurant_id'), 'ingredients', ['restaurant_id'], unique=False)

    op.create_table(
        'waste_log',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('ingredient_id', sa.BigInteger(), nullable=False),
        sa.Column('quantity', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column('reason', sa.String(length=256), nullable=True),
        sa.Column('recorded_by', sa.String(length=64), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id']),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_waste_log_ingredient_id'), 'waste_log', ['ingredient_id'], unique=False)
    op.create_index(op.f('ix_waste_log_restaurant_id'), 'waste_log', ['restaurant_id'], unique=False)

    op.create_table(
        'dish_ingredients',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('dish_id', sa.BigInteger(), nullable=False),
        sa.Column('ingredient_id', sa.BigInteger(), nullable=False),
        sa.Column('quantity_per_dish', sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['dish_id'], ['dishes.id']),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_dish_ingredients_dish_id'), 'dish_ingredients', ['dish_id'], unique=False)
    op.create_index(op.f('ix_dish_ingredients_ingredient_id'), 'dish_ingredients', ['ingredient_id'], unique=False)

    for tbl in ('ingredients', 'waste_log', 'dish_ingredients'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ('ingredients', 'waste_log', 'dish_ingredients'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")

    op.drop_index(op.f('ix_dish_ingredients_ingredient_id'), table_name='dish_ingredients')
    op.drop_index(op.f('ix_dish_ingredients_dish_id'), table_name='dish_ingredients')
    op.drop_table('dish_ingredients')

    op.drop_index(op.f('ix_waste_log_restaurant_id'), table_name='waste_log')
    op.drop_index(op.f('ix_waste_log_ingredient_id'), table_name='waste_log')
    op.drop_table('waste_log')

    op.drop_index(op.f('ix_ingredients_restaurant_id'), table_name='ingredients')
    op.drop_table('ingredients')
