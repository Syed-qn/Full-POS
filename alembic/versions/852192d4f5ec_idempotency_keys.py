"""idempotency_keys

Revision ID: 852192d4f5ec
Revises: s9t0u1v2w3x4
Create Date: 2026-07-07 05:18:08.327600

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '852192d4f5ec'
down_revision: Union[str, Sequence[str], None] = 's9t0u1v2w3x4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('restaurant_id', sa.BigInteger(), nullable=False),
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('method', sa.String(length=10), nullable=False),
        sa.Column('path', sa.String(length=255), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=False),
        sa.Column('response_body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['restaurant_id'], ['restaurants.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_idempotency_keys_restaurant_id'), 'idempotency_keys', ['restaurant_id'], unique=False
    )
    op.create_index(
        'ux_idempotency_keys_restaurant_key_method_path',
        'idempotency_keys',
        ['restaurant_id', 'key', 'method', 'path'],
        unique=True,
    )
    op.execute(
        "CREATE TRIGGER trg_idempotency_keys_updated_at BEFORE UPDATE ON idempotency_keys "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_idempotency_keys_updated_at ON idempotency_keys;")
    op.drop_index('ux_idempotency_keys_restaurant_key_method_path', table_name='idempotency_keys')
    op.drop_index(op.f('ix_idempotency_keys_restaurant_id'), table_name='idempotency_keys')
    op.drop_table('idempotency_keys')
