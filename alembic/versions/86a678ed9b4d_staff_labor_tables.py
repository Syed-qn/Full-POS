"""staff labor tables

Revision ID: 86a678ed9b4d
Revises: 5579c35aeaf5
Create Date: 2026-07-07 09:06:51.680423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '86a678ed9b4d'
down_revision: Union[str, Sequence[str], None] = '5579c35aeaf5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'staff_members',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('phone', sa.String(length=32), nullable=True),
        sa.Column('role', sa.String(length=32), nullable=False, server_default='staff'),
        sa.Column('pin_hash', sa.String(length=256), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_staff_members_restaurant_id'), 'staff_members', ['restaurant_id'], unique=False)

    op.create_table(
        'clock_events',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('staff_id', sa.BigInteger(), nullable=False),
        sa.Column('type', sa.String(length=16), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['staff_id'], ['staff_members.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_clock_events_restaurant_id'), 'clock_events', ['restaurant_id'], unique=False)
    op.create_index(op.f('ix_clock_events_staff_id'), 'clock_events', ['staff_id'], unique=False)

    op.add_column('orders', sa.Column('staff_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key('fk_orders_staff_id_staff_members', 'orders', 'staff_members', ['staff_id'], ['id'])

    for tbl in ('staff_members', 'clock_events'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ('staff_members', 'clock_events'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")

    op.drop_constraint('fk_orders_staff_id_staff_members', 'orders', type_='foreignkey')
    op.drop_column('orders', 'staff_id')

    op.drop_index(op.f('ix_clock_events_staff_id'), table_name='clock_events')
    op.drop_index(op.f('ix_clock_events_restaurant_id'), table_name='clock_events')
    op.drop_table('clock_events')

    op.drop_index(op.f('ix_staff_members_restaurant_id'), table_name='staff_members')
    op.drop_table('staff_members')
