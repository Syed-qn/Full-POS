from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Batch(Base, TimestampMixin):
    """A grouped set of orders assigned to one rider for sequential delivery."""

    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="planned", index=True)
    # planned | picked_up | in_progress | completed
    route: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"stops": [{"order_id": int, "lat": float, "lon": float, "eta_min": int}]}
    total_est_min: Mapped[int | None] = mapped_column(Integer)


class BatchOrder(Base, TimestampMixin):
    """Junction: which orders belong to a batch, in delivery sequence."""

    __tablename__ = "batch_orders"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column(ForeignKey("batches.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RiderLocation(Base, TimestampMixin):
    """Time-series table: each location ping from a rider.

    Hot copy also stored in Redis GEO key ``rider_geo:{restaurant_id}``.
    Retention policy: 30 days raw (matching spec §6 privacy).
    """

    __tablename__ = "rider_locations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    speed: Mapped[float | None] = mapped_column(Float)
    heading: Mapped[float | None] = mapped_column(Float)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class OrderTrackingSession(Base, TimestampMixin):
    """Per-order live tracking session with public + rider access tokens."""

    __tablename__ = "order_tracking_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    tracking_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    rider_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default="active", index=True)
    latest_latitude: Mapped[float | None] = mapped_column(Float)
    latest_longitude: Mapped[float | None] = mapped_column(Float)
    latest_accuracy: Mapped[float | None] = mapped_column(Float)
    latest_speed: Mapped[float | None] = mapped_column(Float)
    latest_heading: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    stopped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Assignment(Base, TimestampMixin):
    """Audit record of every dispatch decision (explainability)."""

    __tablename__ = "assignments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("batches.id"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Explainability payload — why this rider was chosen.
    algorithm_score: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"distance_km": float, "workload_score": float, "area_score": float,
    #  "on_time_pct": float, "composite": float}
