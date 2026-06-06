from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class PredictionRun(Base, TimestampMixin):
    __tablename__ = "prediction_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id"), index=True
    )
    horizon: Mapped[str] = mapped_column(String(16))  # next_1h|breakfast|lunch|dinner|midnight
    target_date: Mapped[date] = mapped_column(Date)
    predicted: Mapped[dict] = mapped_column(JSONB)     # order_count, revenue, dish_demand, avg_distance_km
    actual: Mapped[dict | None] = mapped_column(JSONB, nullable=True)        # backfilled
    accuracy: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)  # 1 - MAPE, 0..1
    model_version: Mapped[str] = mapped_column(String(64))
    adjusted: Mapped[bool] = mapped_column(default=False)  # True if LLM/override applied
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_prediction_runs_rest_date_horizon", "restaurant_id", "target_date", "horizon"),
    )


class ModelRegistry(Base, TimestampMixin):
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id"), index=True
    )
    model_type: Mapped[str] = mapped_column(String(32))   # rolling | lightgbm (future)
    version: Mapped[str] = mapped_column(String(64))
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)  # mape, n_samples, etc.


class ManagerOverride(Base, TimestampMixin):
    __tablename__ = "manager_overrides"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("restaurants.id"), index=True
    )
    text: Mapped[str] = mapped_column(Text)                  # plain English from manager
    parsed_effect: Mapped[dict] = mapped_column(JSONB)       # DSL: {horizon, dow, *_delta, *_mult}
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    active_to: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_to_runs: Mapped[list] = mapped_column(JSONB, default=list)  # run ids the override touched
    enabled: Mapped[bool] = mapped_column(default=True)
