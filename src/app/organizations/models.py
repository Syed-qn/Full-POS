"""Organization, stock transfers, and Category 11 franchise entities."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    owner_email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    # Franchise economics
    royalty_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), default=Decimal("0.00"), server_default="0"
    )
    default_currency: Mapped[str] = mapped_column(
        String(8), default="AED", server_default="AED"
    )
    default_locale: Mapped[str] = mapped_column(
        String(16), default="en", server_default="en"
    )
    # fx_rates: {"USD": 0.27, "EUR": 0.25} as AED→foreign multipliers; dashboard locale, etc.
    settings: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class StockTransfer(Base, TimestampMixin):
    """A stock movement between two branches (Restaurant rows) of the same org."""

    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    from_restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    to_restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)


class StockTransferLine(Base, TimestampMixin):
    __tablename__ = "stock_transfer_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    transfer_id: Mapped[int] = mapped_column(ForeignKey("stock_transfers.id"), index=True)
    ingredient_name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16))
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3))


class OrgMenuItem(Base, TimestampMixin):
    """HQ master menu item — published out to branch restaurant menus."""

    __tablename__ = "org_menu_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    dish_number: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    name_ar: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(String(2000))
    category: Mapped[str | None] = mapped_column(String(128))
    base_price_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Optional recipe/metadata JSON
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class OrgBranchPrice(Base, TimestampMixin):
    """Branch-specific price override for a master menu item."""

    __tablename__ = "org_branch_prices"
    __table_args__ = (
        UniqueConstraint(
            "org_menu_item_id", "restaurant_id", name="uq_org_branch_price"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    org_menu_item_id: Mapped[int] = mapped_column(ForeignKey("org_menu_items.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    price_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))


class OrgMenuPublishJob(Base, TimestampMixin):
    """Menu publish approval workflow: pending → approved → published | rejected."""

    __tablename__ = "org_menu_publish_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(24), default="pending", server_default="pending", index=True
    )
    # list of restaurant_ids to publish to; empty = all branches
    target_restaurant_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # list of org_menu_item ids; empty = all active
    org_menu_item_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    requested_by: Mapped[str | None] = mapped_column(String(128))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(String(512))
    result: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrgCustomer(Base, TimestampMixin):
    """Org-wide customer identity (shared across branches)."""

    __tablename__ = "org_customers"
    __table_args__ = (
        UniqueConstraint("organization_id", "phone", name="uq_org_customers_phone"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    loyalty_points: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_orders: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_spend_aed: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0"), server_default="0"
    )
    preferred_locale: Mapped[str | None] = mapped_column(String(16))
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class OrgPromotion(Base, TimestampMixin):
    """HQ-controlled promotion pushed to selected branches as coupons."""

    __tablename__ = "org_promotions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    discount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0"))
    discount_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # active | paused | expired
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    # empty = all branches
    target_restaurant_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # map restaurant_id -> coupon_id after push
    pushed_coupon_ids: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrgMember(Base, TimestampMixin):
    """HQ / regional roles with optional branch scope."""

    __tablename__ = "org_members"
    __table_args__ = (
        UniqueConstraint("organization_id", "email", name="uq_org_members_email"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    email: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(128))
    # hq_admin | regional_manager | branch_manager | auditor
    role: Mapped[str] = mapped_column(String(32), default="branch_manager")
    # empty = all branches for hq_admin; otherwise scoped restaurant ids
    branch_ids: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    pin_hash: Mapped[str | None] = mapped_column(String(256))


class CentralKitchenRequest(Base, TimestampMixin):
    """Branch → central kitchen production / transfer request."""

    __tablename__ = "central_kitchen_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    from_restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    central_kitchen_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    # pending | in_production | ready | shipped | cancelled
    status: Mapped[str] = mapped_column(String(24), default="pending", server_default="pending")
    items: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    notes: Mapped[str | None] = mapped_column(Text)
