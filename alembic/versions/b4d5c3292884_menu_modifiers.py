"""menu modifiers

Revision ID: b4d5c3292884
Revises: fbc29877119c
Create Date: 2026-07-07 17:26:09.184392

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b4d5c3292884'
down_revision: Union[str, Sequence[str], None] = 'fbc29877119c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'modifier_groups',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('dish_id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('min_select', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_select', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('required', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['dish_id'], ['dishes.id']),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_modifier_groups_dish_id'), 'modifier_groups', ['dish_id'], unique=False)
    op.create_index(op.f('ix_modifier_groups_restaurant_id'), 'modifier_groups', ['restaurant_id'], unique=False)

    op.create_table(
        'modifiers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('group_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('price_delta_aed', sa.Numeric(precision=8, scale=2), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['group_id'], ['modifier_groups.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_modifiers_group_id'), 'modifiers', ['group_id'], unique=False)

    op.add_column(
        'order_items',
        sa.Column('selected_modifiers', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False),
    )

    for tbl in ('modifier_groups', 'modifiers'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ('modifier_groups', 'modifiers'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")

    op.drop_column('order_items', 'selected_modifiers')

    op.drop_index(op.f('ix_modifiers_group_id'), table_name='modifiers')
    op.drop_table('modifiers')

    op.drop_index(op.f('ix_modifier_groups_restaurant_id'), table_name='modifier_groups')
    op.drop_index(op.f('ix_modifier_groups_dish_id'), table_name='modifier_groups')
    op.drop_table('modifier_groups')
