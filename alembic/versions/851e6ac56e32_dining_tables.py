"""dining tables

Revision ID: 851e6ac56e32
Revises: 040d78934696
Create Date: 2026-07-07 08:40:40.041729

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '851e6ac56e32'
down_revision: Union[str, Sequence[str], None] = '040d78934696'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tables',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('label', sa.String(length=32), nullable=False),
        sa.Column('seats', sa.Integer(), nullable=False, server_default='2'),
        sa.Column('pos_x', sa.Float(), nullable=False, server_default='0'),
        sa.Column('pos_y', sa.Float(), nullable=False, server_default='0'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='available'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tables_restaurant_id'), 'tables', ['restaurant_id'], unique=False)

    op.add_column('orders', sa.Column('table_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_orders_table_id_tables', 'orders', 'tables', ['table_id'], ['id'])

    op.execute(
        "CREATE TRIGGER trg_tables_updated_at BEFORE UPDATE ON tables "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_tables_updated_at ON tables;")
    op.drop_constraint('fk_orders_table_id_tables', 'orders', type_='foreignkey')
    op.drop_column('orders', 'table_id')
    op.drop_index(op.f('ix_tables_restaurant_id'), table_name='tables')
    op.drop_table('tables')
