"""menu combos

Revision ID: e794d12a05a8
Revises: 9be09f780ce3
Create Date: 2026-07-07 18:29:23.636064

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e794d12a05a8'
down_revision: Union[str, Sequence[str], None] = '9be09f780ce3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'combos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('menu_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('price_aed', sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column('is_available', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['menu_id'], ['menus.id']),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_combos_menu_id'), 'combos', ['menu_id'], unique=False)
    op.create_index(op.f('ix_combos_restaurant_id'), 'combos', ['restaurant_id'], unique=False)

    op.create_table(
        'combo_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('combo_id', sa.Integer(), nullable=False),
        sa.Column('dish_id', sa.BigInteger(), nullable=False),
        sa.Column('qty', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['combo_id'], ['combos.id']),
        sa.ForeignKeyConstraint(['dish_id'], ['dishes.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_combo_items_combo_id'), 'combo_items', ['combo_id'], unique=False)
    op.create_index(op.f('ix_combo_items_dish_id'), 'combo_items', ['dish_id'], unique=False)

    for tbl in ('combos', 'combo_items'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ('combos', 'combo_items'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")

    op.drop_index(op.f('ix_combo_items_dish_id'), table_name='combo_items')
    op.drop_index(op.f('ix_combo_items_combo_id'), table_name='combo_items')
    op.drop_table('combo_items')

    op.drop_index(op.f('ix_combos_restaurant_id'), table_name='combos')
    op.drop_index(op.f('ix_combos_menu_id'), table_name='combos')
    op.drop_table('combos')
