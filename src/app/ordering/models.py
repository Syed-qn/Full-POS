from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    # (restaurant_id, phone) is THE customer-resolution lookup — unique per tenant
    __table_args__ = (UniqueConstraint("restaurant_id", "phone", name="uq_customers_restaurant_phone"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    first_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_order_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # {"0": "12:00", "5": "19:30"} — keyed by weekday int 0=Mon
    usual_order_times: Mapped[dict] = mapped_column(JSONB, default=dict)
    tags: Mapped[dict] = mapped_column(JSONB, default=dict)
    total_orders: Mapped[int] = mapped_column(Integer, default=0)
    total_spend: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    # Loyalty (Phase 1). tier is a denormalized cache of the nightly/on-delivery
    # RFM+Monetary computation; locked = manager manually set it (recompute skips).
    # reward_anchor = total_orders at tier entry, for "every N orders" reward counting.
    loyalty_tier: Mapped[str | None] = mapped_column(String(12))
    loyalty_tier_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loyalty_tier_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    loyalty_reward_anchor: Mapped[int] = mapped_column(Integer, default=0)


class CustomerAddress(Base, TimestampMixin):
    __tablename__ = "customer_addresses"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    # lat/lng stored as plain floats; PostGIS geography column added in logistics phase
    latitude: Mapped[float | None] = mapped_column()
    longitude: Mapped[float | None] = mapped_column()
    room_apartment: Mapped[str | None] = mapped_column(String(128))
    building: Mapped[str | None] = mapped_column(String(128))
    receiver_name: Mapped[str | None] = mapped_column(String(128))
    additional_details: Mapped[str | None] = mapped_column(String(512))
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    # open-orders-for-restaurant is the hot dispatch/SLA query path
    __table_args__ = (Index("ix_orders_restaurant_status", "restaurant_id", "status"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")

    address_id: Mapped[int | None] = mapped_column(ForeignKey("customer_addresses.id"))
    additional_details: Mapped[str | None] = mapped_column(Text)

    # Dispatch (Phase 4): nullable until the dispatch engine assigns a rider.
    rider_id: Mapped[int | None] = mapped_column(ForeignKey("riders.id"), index=True)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    delivery_fee_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    distance_km: Mapped[float | None] = mapped_column()

    weather_delay_disclosed: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Kitchen "plate by" deadline = sla_confirmed_at + customer SLA − drive time to the
    # delivery address − handling − batch safety. Distance-driven, not hardcoded. Null
    # when the order has no geocoded drop-off (can't compute a drive leg).
    prep_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Estimated minutes to cook this order (slowest dish gates readiness). With
    # prep_deadline it yields "start cooking by" = prep_deadline − cook_estimate_minutes.
    cook_estimate_minutes: Mapped[int | None] = mapped_column(Integer)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late: Mapped[bool | None] = mapped_column(Boolean)

    coupon_id: Mapped[int | None] = mapped_column(BigInteger)
    # Wallet store-credit applied to this order (held at confirm, captured on
    # delivery, released on cancel). COD due = total - wallet_applied_aed.
    wallet_applied_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))

    # Resale fields
    resale_of_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    # SHA-256 hex of phone + address used to exclude original customer from resale
    exclusion_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    cancellation_reason: Mapped[str | None] = mapped_column(String(256))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Partner POS sync (Phase 1): POS ack + push tracking.
    pos_order_id: Mapped[str | None] = mapped_column(String(64))
    pos_pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pos_push_status: Mapped[str | None] = mapped_column(String(16))  # pending|acked|failed


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    # Snapshot fields — captured at order time, not FK-joined at read time
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    dish_number: Mapped[int] = mapped_column(Integer)
    dish_name: Mapped[str] = mapped_column(String(256))
    # Chosen serving-size label (e.g. "4 serve"), snapshotted like dish_name. Null for
    # flat dishes with no variants. price_aed already snapshots the resolved variant price.
    variant_name: Mapped[str | None] = mapped_column(String(128))
    price_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(String(512))  # verbatim special request
