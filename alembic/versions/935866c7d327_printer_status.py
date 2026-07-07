"""printer status

Revision ID: 935866c7d327
Revises: e00d0260aad3
Create Date: 2026-07-07 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '935866c7d327'
down_revision: Union[str, Sequence[str], None] = 'e00d0260aad3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'printer_statuses',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('station_id', sa.BigInteger(), nullable=False),
        sa.Column('healthy', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('last_heartbeat_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['station_id'], ['kitchen_stations.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_printer_statuses_restaurant_id'), 'printer_statuses', ['restaurant_id'], unique=False)
    op.create_index(op.f('ix_printer_statuses_station_id'), 'printer_statuses', ['station_id'], unique=False)

    op.execute(
        "CREATE TRIGGER trg_printer_statuses_updated_at BEFORE UPDATE ON printer_statuses "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_printer_statuses_updated_at ON printer_statuses;")
    op.drop_index(op.f('ix_printer_statuses_station_id'), table_name='printer_statuses')
    op.drop_index(op.f('ix_printer_statuses_restaurant_id'), table_name='printer_statuses')
    op.drop_table('printer_statuses')
