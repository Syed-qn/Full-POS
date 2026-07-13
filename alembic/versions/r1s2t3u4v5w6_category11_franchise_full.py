"""category11 multi-branch franchise full

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "r1s2t3u4v5w6"
down_revision = "q0r1s2t3u4v5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("royalty_pct", sa.Numeric(5, 2), server_default="0", nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column("default_currency", sa.String(8), server_default="AED", nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column("default_locale", sa.String(16), server_default="en", nullable=False),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )

    op.add_column("restaurants", sa.Column("region", sa.String(64), nullable=True))
    op.add_column(
        "restaurants",
        sa.Column("currency", sa.String(8), server_default="AED", nullable=False),
    )
    op.add_column(
        "restaurants",
        sa.Column("locale", sa.String(16), server_default="en", nullable=False),
    )
    op.add_column(
        "restaurants",
        sa.Column(
            "is_central_kitchen",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )
    op.create_index("ix_restaurants_region", "restaurants", ["region"])

    op.create_table(
        "org_menu_items",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("dish_number", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("name_ar", sa.String(255), nullable=True),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column("category", sa.String(128), nullable=True),
        sa.Column("base_price_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "org_branch_prices",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("org_menu_item_id", sa.BigInteger(), sa.ForeignKey("org_menu_items.id"), nullable=False, index=True),
        sa.Column("restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id"), nullable=False, index=True),
        sa.Column("price_aed", sa.Numeric(8, 2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("org_menu_item_id", "restaurant_id", name="uq_org_branch_price"),
    )
    op.create_table(
        "org_menu_publish_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False, index=True),
        sa.Column("target_restaurant_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("org_menu_item_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("requested_by", sa.String(128), nullable=True),
        sa.Column("approved_by", sa.String(128), nullable=True),
        sa.Column("notes", sa.String(512), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "org_customers",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("phone", sa.String(32), nullable=False, index=True),
        sa.Column("name", sa.String(128), nullable=True),
        sa.Column("loyalty_points", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_orders", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_spend_aed", sa.Numeric(12, 2), server_default="0", nullable=False),
        sa.Column("preferred_locale", sa.String(16), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("organization_id", "phone", name="uq_org_customers_phone"),
    )
    op.create_table(
        "org_promotions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("discount_aed", sa.Numeric(8, 2), server_default="0", nullable=False),
        sa.Column("discount_pct", sa.Numeric(5, 2), nullable=True),
        sa.Column("status", sa.String(16), server_default="active", nullable=False),
        sa.Column("target_restaurant_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("pushed_coupon_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_table(
        "org_members",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("role", sa.String(32), server_default="branch_manager", nullable=False),
        sa.Column("branch_ids", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("pin_hash", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("organization_id", "email", name="uq_org_members_email"),
    )
    op.create_table(
        "central_kitchen_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.BigInteger(), sa.ForeignKey("organizations.id"), nullable=False, index=True),
        sa.Column("from_restaurant_id", sa.BigInteger(), sa.ForeignKey("restaurants.id"), nullable=False, index=True),
        sa.Column("central_kitchen_id", sa.BigInteger(), sa.ForeignKey("restaurants.id"), nullable=False, index=True),
        sa.Column("status", sa.String(24), server_default="pending", nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    for table in (
        "org_menu_items",
        "org_branch_prices",
        "org_menu_publish_jobs",
        "org_customers",
        "org_promotions",
        "org_members",
        "central_kitchen_requests",
    ):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};"
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            """
        )


def downgrade() -> None:
    for table in (
        "central_kitchen_requests",
        "org_members",
        "org_promotions",
        "org_customers",
        "org_menu_publish_jobs",
        "org_branch_prices",
        "org_menu_items",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table};")
        op.drop_table(table)
    op.drop_index("ix_restaurants_region", table_name="restaurants")
    op.drop_column("restaurants", "is_central_kitchen")
    op.drop_column("restaurants", "locale")
    op.drop_column("restaurants", "currency")
    op.drop_column("restaurants", "region")
    op.drop_column("organizations", "settings")
    op.drop_column("organizations", "default_locale")
    op.drop_column("organizations", "default_currency")
    op.drop_column("organizations", "royalty_pct")
