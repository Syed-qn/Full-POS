"""organizations multi branch

Revision ID: 05fede78a55e
Revises: 31388336ef27
Create Date: 2026-07-07 09:21:16.737243

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '05fede78a55e'
down_revision: Union[str, Sequence[str], None] = '31388336ef27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'organizations',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('owner_email', sa.String(length=255), nullable=False),
        sa.Column('password_hash', sa.String(length=255), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_organizations_owner_email'), 'organizations', ['owner_email'], unique=True)

    op.add_column('restaurants', sa.Column('organization_id', sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        'fk_restaurants_organization_id_organizations', 'restaurants', 'organizations', ['organization_id'], ['id']
    )

    op.execute(
        "CREATE TRIGGER trg_organizations_updated_at BEFORE UPDATE ON organizations "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at();"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_organizations_updated_at ON organizations;")
    op.drop_constraint('fk_restaurants_organization_id_organizations', 'restaurants', type_='foreignkey')
    op.drop_column('restaurants', 'organization_id')
    op.drop_index(op.f('ix_organizations_owner_email'), table_name='organizations')
    op.drop_table('organizations')
