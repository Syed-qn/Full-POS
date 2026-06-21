import copy
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin

DEFAULT_SETTINGS: dict = {
    "max_orders_per_batch": 3,
    "max_items_per_order": 20,
    "delivery_fee_tiers": [
        {"max_km": 3, "fee_aed": 0},
        {"max_km": 5, "fee_aed": 5},
        {"max_km": 10, "fee_aed": 10},
    ],
    "max_radius_km": 10,
    # Dispatch engine per restaurant (spec §4.3). "greedy" = proximity batching
    # (default, safe). "ortools" = SLA-first VRP route optimizer (opt-in pilot).
    # Existing rows without this key read as "greedy" via .get() in the service.
    "dispatch_engine": "greedy",
    # Kitchen prep deadline tuning (minutes), read via .get() with these defaults.
    # handling = pickup/hand-off slack reserved for the rider at the restaurant;
    # batch_safety = margin so an order that later joins a batch (extra inter-stop
    # drive) still makes the SLA. Both subtracted from the drive budget — not hardcoded.
    "prep_handling_minutes": 5,
    "batch_safety_minutes": 5,
}


class Restaurant(Base, TimestampMixin):
    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    settings: Mapped[dict] = mapped_column(JSONB, default=lambda: copy.deepcopy(DEFAULT_SETTINGS))


class Rider(Base, TimestampMixin):
    __tablename__ = "riders"
    __table_args__ = (UniqueConstraint("restaurant_id", "phone"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    phone: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="available")
    # available | on_delivery | off_shift | deactivated
    # Native rider app (Android) auth: the rider pairs ONCE with a short code sent
    # via WhatsApp; the app then stores `device_token` (long-lived bearer) and
    # streams background GPS. pairing_code is the one-time, expiring pairing code.
    device_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, index=True, nullable=True
    )
    pairing_code: Mapped[str | None] = mapped_column(String(12), index=True, nullable=True)
    pairing_code_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Expo push token (native app) — set by the app after it registers for
    # notifications, used to wake the rider when a delivery is assigned.
    push_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Rolling delivery performance (Phase 4) — feeds dispatch scoring.
    performance: Mapped[dict] = mapped_column(
        JSONB,
        default=lambda: {
            "on_time_pct": 100.0,
            "avg_delivery_min": 25,
            "total_deliveries": 0,
        },
    )
