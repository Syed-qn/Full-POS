"""ingredient par level and substitutes

Adds ingredients.par_level (target restock-up-to level, distinct from
low_stock_threshold which is the trigger point) and a new ingredient_substitutes
table used to suggest swap-ins when the primary ingredient is out of stock.

Revision ID: u2v3w4x5y6z7
Revises: 122f2270dfbc
Create Date: 2026-07-08
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'u2v3w4x5y6z7'
down_revision: Union[str, Sequence[str], None] = '122f2270dfbc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'ingredients',
        sa.Column('par_level', sa.Numeric(precision=10, scale=3), nullable=False, server_default='0'),
    )

    op.create_table(
        'ingredient_substitutes',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('ingredient_id', sa.BigInteger(), nullable=False),
        sa.Column('substitute_ingredient_id', sa.BigInteger(), nullable=False),
        sa.Column('notes', sa.String(length=256), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['ingredient_id'], ['ingredients.id']),
        sa.ForeignKeyConstraint(['substitute_ingredient_id'], ['ingredients.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_ingredient_substitutes_restaurant_id'), 'ingredient_substitutes', ['restaurant_id'], unique=False,
    )
    op.create_index(
        op.f('ix_ingredient_substitutes_ingredient_id'), 'ingredient_substitutes', ['ingredient_id'], unique=False,
    )
    op.create_index(
        op.f('ix_ingredient_substitutes_substitute_ingredient_id'),
        'ingredient_substitutes', ['substitute_ingredient_id'], unique=False,
    )

    op.execute(
        "CREATE TRIGGER trg_ingredient_substitutes_updated_at BEFORE UPDATE ON ingredient_substitutes "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ingredient_substitutes_updated_at ON ingredient_substitutes;")

    op.drop_index(op.f('ix_ingredient_substitutes_substitute_ingredient_id'), table_name='ingredient_substitutes')
    op.drop_index(op.f('ix_ingredient_substitutes_ingredient_id'), table_name='ingredient_substitutes')
    op.drop_index(op.f('ix_ingredient_substitutes_restaurant_id'), table_name='ingredient_substitutes')
    op.drop_table('ingredient_substitutes')

    op.drop_column('ingredients', 'par_level')
