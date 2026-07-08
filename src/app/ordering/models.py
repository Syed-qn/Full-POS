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
    # Denormalized typical order time label (recomputed from orders on stat refresh).
    usual_order_time: Mapped[str | None] = mapped_column(String(64))
    # Loyalty (Phase 1). tier is a denormalized cache of the nightly/on-delivery
    # RFM+Monetary computation; locked = manager manually set it (recompute skips).
    # reward_anchor = total_orders at tier entry, for "every N orders" reward counting.
    loyalty_tier: Mapped[str | None] = mapped_column(String(12))
    loyalty_tier_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    loyalty_tier_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    loyalty_reward_anchor: Mapped[int] = mapped_column(Integer, default=0)
    # Referral program: who referred this customer, set once at signup/first-order
    # time by app.loyalty.referrals.redeem_referral and never changed after.
    referred_by_customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))


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
    __table_args__ = (
        Index("ix_orders_restaurant_status", "restaurant_id", "status"),
        Index("ix_orders_restaurant_created_at", "restaurant_id", "created_at"),
        # TX-13/F114: order numbers must be unique per tenant — a racy allocation
        # (or a reset) must never silently produce a duplicate #R1-0001.
        UniqueConstraint("restaurant_id", "order_number", name="uq_orders_restaurant_order_number"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")

    address_id: Mapped[int | None] = mapped_column(ForeignKey("customer_addresses.id"))
    # Dine-in binding — null for delivery orders. Set when an order is opened
    # against a physical table (see app.tables).
    table_id: Mapped[int | None] = mapped_column(ForeignKey("tables.id"))
    # Sales-per-server attribution — null when no staff member is tracked (e.g. self-service).
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_members.id"))
    # Third-party channel this order arrived through. Null = native WhatsApp order.
    aggregator_source: Mapped[str | None] = mapped_column(String(24))
    aggregator_order_ref: Mapped[str | None] = mapped_column(String(128))
    additional_details: Mapped[str | None] = mapped_column(Text)

    # Dispatch (Phase 4): nullable until the dispatch engine assigns a rider.
    rider_id: Mapped[int | None] = mapped_column(ForeignKey("riders.id"), index=True)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    delivery_fee_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    distance_km: Mapped[float | None] = mapped_column()
    # How ``distance_km`` was derived: "road" (geo provider) or "haversine_fallback"
    # (provider failed / unconfigured). Persisted so fee basis is auditable and a
    # degraded quote is visible to ops (F112/F31). Null on legacy rows.
    distance_source: Mapped[str | None] = mapped_column(String(32))

    weather_delay_disclosed: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Kitchen "plate by" deadline = sla_confirmed_at + customer SLA − drive time to the
    # delivery address − handling − batch safety. Distance-driven, not hardcoded. Null
    # when the order has no geocoded drop-off (can't compute a drive leg).
    prep_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Pre-order / scheduled delivery — customer wants this at a future time, not
    # ASAP. Null = normal immediate order. Kitchen/dispatch timing (prep_deadline,
    # sla_deadline) still only kick in once the order is actually confirmed for
    # cooking near scheduled_for — that trigger is a follow-up, not this field.
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Estimated minutes to cook this order (slowest dish gates readiness). With
    # prep_deadline it yields "start cooking by" = prep_deadline − cook_estimate_minutes.
    cook_estimate_minutes: Mapped[int | None] = mapped_column(Integer)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late: Mapped[bool | None] = mapped_column(Boolean)

    # Delivery proof (additive, informational — neither gates the delivery FSM).
    # A URL/path string the rider app uploads to; no blob-storage vendor is wired
    # in yet, so this just stores whatever URL string is handed to us.
    delivery_photo_url: Mapped[str | None] = mapped_column(String(512))
    # 4-digit code, auto-generated when the order reaches "arriving" (see
    # app.dispatch.delivery.advance_delivery). Verifying it is informational only.
    delivery_otp: Mapped[str | None] = mapped_column(String(4))
    delivery_otp_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    coupon_id: Mapped[int | None] = mapped_column(BigInteger)
    # Coupon discount applied to this order (AED). Persisted so ``recompute_order_total``
    # can re-apply it verbatim on every modify/redeem without re-deriving from the coupon
    # row, keeping summary math == confirm math == door cash (F26/F41).
    coupon_discount_aed: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0"
    )
    # Wallet store-credit applied to this order (held at confirm, captured on
    # delivery, released on cancel). COD due = total - wallet_applied_aed.
    wallet_applied_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))

    # UAE VAT — snapshotted at confirm time so a later platform rate change
    # never retroactively alters an already-issued invoice.
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), default=Decimal("0.0500"))
    vat_amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))

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
    # Partial cancellation: a manager can cancel a single line without voiding the
    # whole order. Cancelled items are excluded from order.subtotal/total but kept
    # on the row (audit trail) rather than deleted.
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    cancelled_reason: Mapped[str | None] = mapped_column(String(256))
    # Snapshot of chosen modifiers at order time — [{"name": str, "price_delta_aed": str}, ...].
    selected_modifiers: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # KDS: per-item kitchen ticket status (received|preparing|ready|bumped).
    kitchen_status: Mapped[str] = mapped_column(String(16), default="received")
    bumped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Station resolved at ticket-creation time — snapshotted so a later station
    # reassignment doesn't retroactively move an in-flight ticket.
    station_id_snapshot: Mapped[int | None] = mapped_column(ForeignKey("kitchen_stations.id"))
    # Allergen tags snapshotted from Dish.allergens at add-item time (same pattern as
    # dish_name/price_aed above) so a later menu edit never retroactively changes an
    # already-placed order's ticket. KDS renders this as a warning badge.
    allergens_snapshot: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    # KDS packaging/quality checklist (Phase: KDS enhancements). Both default False;
    # set true via dedicated endpoints once kitchen staff confirm each step.
    packaging_checked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    quality_checked: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
