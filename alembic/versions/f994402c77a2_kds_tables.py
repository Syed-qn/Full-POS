"""kds tables

Revision ID: f994402c77a2
Revises: 852192d4f5ec
Create Date: 2026-07-07 08:02:23.123625

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f994402c77a2'
down_revision: Union[str, Sequence[str], None] = '852192d4f5ec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'kitchen_stations',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.Column('printer_ip', sa.String(length=64), nullable=True),
        sa.Column('printer_port', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_kitchen_stations_restaurant_id'), 'kitchen_stations', ['restaurant_id'], unique=False)

    op.create_table(
        'category_station_defaults',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('category', sa.String(length=128), nullable=False),
        sa.Column('station_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['station_id'], ['kitchen_stations.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('restaurant_id', 'category'),
    )
    op.create_index(
        op.f('ix_category_station_defaults_restaurant_id'), 'category_station_defaults', ['restaurant_id'], unique=False
    )

    op.create_table(
        'print_jobs',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('station_id', sa.BigInteger(), nullable=False),
        sa.Column('order_id', sa.BigInteger(), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['order_id'], ['orders.id']),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['station_id'], ['kitchen_stations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_print_jobs_order_id'), 'print_jobs', ['order_id'], unique=False)
    op.create_index(op.f('ix_print_jobs_restaurant_id'), 'print_jobs', ['restaurant_id'], unique=False)
    op.create_index(op.f('ix_print_jobs_station_id'), 'print_jobs', ['station_id'], unique=False)

    op.add_column('dishes', sa.Column('station_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_dishes_station_id_kitchen_stations', 'dishes', 'kitchen_stations', ['station_id'], ['id']
    )

    op.add_column(
        'order_items',
        sa.Column('kitchen_status', sa.String(length=16), nullable=False, server_default='received'),
    )
    op.add_column('order_items', sa.Column('bumped_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('order_items', sa.Column('station_id_snapshot', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_order_items_station_id_snapshot_kitchen_stations',
        'order_items', 'kitchen_stations', ['station_id_snapshot'], ['id'],
    )

    for tbl in ('kitchen_stations', 'category_station_defaults', 'print_jobs'):
        op.execute(
            f"CREATE TRIGGER trg_{tbl}_updated_at BEFORE UPDATE ON {tbl} "
            f"FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
        )


def downgrade() -> None:
    for tbl in ('kitchen_stations', 'category_station_defaults', 'print_jobs'):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{tbl}_updated_at ON {tbl};")

    op.drop_constraint('fk_order_items_station_id_snapshot_kitchen_stations', 'order_items', type_='foreignkey')
    op.drop_column('order_items', 'station_id_snapshot')
    op.drop_column('order_items', 'bumped_at')
    op.drop_column('order_items', 'kitchen_status')

    op.drop_constraint('fk_dishes_station_id_kitchen_stations', 'dishes', type_='foreignkey')
    op.drop_column('dishes', 'station_id')

    op.drop_index(op.f('ix_print_jobs_station_id'), table_name='print_jobs')
    op.drop_index(op.f('ix_print_jobs_restaurant_id'), table_name='print_jobs')
    op.drop_index(op.f('ix_print_jobs_order_id'), table_name='print_jobs')
    op.drop_table('print_jobs')

    op.drop_index(op.f('ix_category_station_defaults_restaurant_id'), table_name='category_station_defaults')
    op.drop_table('category_station_defaults')

    op.drop_index(op.f('ix_kitchen_stations_restaurant_id'), table_name='kitchen_stations')
    op.drop_table('kitchen_stations')
