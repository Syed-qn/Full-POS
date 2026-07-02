"""email login + nullable whatsapp phone

Login identity moves from phone → email. The phone column becomes the WhatsApp
display number (set on Meta connect) and is now nullable (a freshly signed-up
restaurant has none until it connects). Existing rows get a placeholder email so
the NOT NULL/unique constraints hold; real emails are set afterwards.

Revision ID: p9c0d1e2f3g4
Revises: o8b9c0d1e2f3
Create Date: 2026-07-02
"""
from alembic import op
import sqlalchemy as sa

revision = "p9c0d1e2f3g4"
down_revision = "o8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Add email nullable, backfill a unique placeholder, then enforce NOT NULL.
    op.add_column("restaurants", sa.Column("email", sa.String(length=255), nullable=True))
    op.execute(
        "UPDATE restaurants "
        "SET email = 'legacy+' || id || '@placeholder.local' "
        "WHERE email IS NULL"
    )
    op.alter_column("restaurants", "email", existing_type=sa.String(length=255), nullable=False)
    op.create_index("ix_restaurants_email", "restaurants", ["email"], unique=True)

    # 2) phone → nullable (WhatsApp number, set on Meta connect). Unique index stays.
    op.alter_column("restaurants", "phone", existing_type=sa.String(length=32), nullable=True)


def downgrade() -> None:
    op.alter_column("restaurants", "phone", existing_type=sa.String(length=32), nullable=False)
    op.drop_index("ix_restaurants_email", table_name="restaurants")
    op.drop_column("restaurants", "email")
