from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Coupon(Base, TimestampMixin):
    """A discount coupon.

    Two shapes share this table:
      * **apology** (kind='single_use'): minted per SLA breach, tied to a
        customer + the order that caused it (back-compat with the original
        late-delivery flow).
      * **campaign** (kind='multi_use'): manager-created promo redeemable by many
        customers under caps/limits; customer_id/order_id null at creation.

    Codes are unique PER TENANT (two restaurants may both use "WELCOME10").
    """

    __tablename__ = "coupons"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "code", name="uq_coupons_restaurant_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    # Set for single-use apology coupons; null for campaign coupons.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    # Cause — the order that triggered an apology coupon. Null for campaigns.
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)

    # single_use | multi_use
    kind: Mapped[str] = mapped_column(String(12), default="single_use")
    # fixed | percent
    discount_type: Mapped[str] = mapped_column(String(8), default="fixed")
    # Fixed-amount discount (AED). Null for percent coupons.
    discount_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    # Percentage discount (e.g. 15.00 = 15%). Null for fixed coupons.
    percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    # Cap on the absolute discount a percent coupon may apply (anti-blowup).
    max_discount_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    # Eligibility floor — order subtotal must be >= this.
    min_order_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    # whole_order | delivery_fee | specific_dishes
    applies_to: Mapped[str] = mapped_column(String(16), default="whole_order")

    per_customer_limit: Mapped[int | None] = mapped_column(Integer)
    total_redemption_limit: Mapped[int | None] = mapped_column(Integer)

    # active | paused | exhausted | expired | issued | redeemed
    status: Mapped[str] = mapped_column(String(16), default="issued", index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_by: Mapped[str | None] = mapped_column(String(64))

    # Back-compat single-use redemption pointers (apology flow).
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_on_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))


class CouponRedemption(Base, TimestampMixin):
    """Append-only ledger of coupon uses — THE source of truth for limit
    enforcement and dup-prevention. A redemption is created atomically with a
    unique ``idempotency_key``; replays return the existing row."""

    __tablename__ = "coupon_redemptions"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key", name="uq_coupon_redemptions_idempotency_key"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    coupon_id: Mapped[int] = mapped_column(ForeignKey("coupons.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int] = mapped_column(BigInteger, index=True)
    discount_applied_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    idempotency_key: Mapped[str] = mapped_column(String(128))
