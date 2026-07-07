"""staff shifts

Revision ID: 324ef2b2bb9b
Revises: 9be09f780ce3
Create Date: 2026-07-07 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '324ef2b2bb9b'
down_revision: Union[str, Sequence[str], None] = '9be09f780ce3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'shifts',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('staff_id', sa.BigInteger(), nullable=False),
        sa.Column('scheduled_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('scheduled_end', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.ForeignKeyConstraint(['staff_id'], ['staff_members.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_shifts_restaurant_id'), 'shifts', ['restaurant_id'], unique=False)
    op.create_index(op.f('ix_shifts_staff_id'), 'shifts', ['staff_id'], unique=False)

    op.execute(
        "CREATE TRIGGER trg_shifts_updated_at BEFORE UPDATE ON shifts "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_shifts_updated_at ON shifts;")
    op.drop_index(op.f('ix_shifts_staff_id'), table_name='shifts')
    op.drop_index(op.f('ix_shifts_restaurant_id'), table_name='shifts')
    op.drop_table('shifts')
