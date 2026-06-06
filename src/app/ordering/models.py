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
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

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

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_number: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    priority: Mapped[str] = mapped_column(String(16), default="normal")

    address_id: Mapped[int | None] = mapped_column(ForeignKey("customer_addresses.id"))
    additional_details: Mapped[str | None] = mapped_column(Text)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    delivery_fee_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    total: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    distance_km: Mapped[float | None] = mapped_column()

    weather_delay_disclosed: Mapped[bool] = mapped_column(Boolean, default=False)
    sla_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    promised_eta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    late: Mapped[bool | None] = mapped_column(Boolean)

    coupon_id: Mapped[int | None] = mapped_column(BigInteger)

    # Resale fields
    resale_of_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    # SHA-256 hex of phone + address used to exclude original customer from resale
    exclusion_hash: Mapped[str | None] = mapped_column(String(64), index=True)

    cancellation_reason: Mapped[str | None] = mapped_column(String(256))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    # Snapshot fields — captured at order time, not FK-joined at read time
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    dish_number: Mapped[int] = mapped_column(Integer)
    dish_name: Mapped[str] = mapped_column(String(256))
    price_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    qty: Mapped[int] = mapped_column(Integer, default=1)
    notes: Mapped[str | None] = mapped_column(String(512))  # verbatim special request
