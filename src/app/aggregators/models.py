"""Persisted channel sync logs + aggregator settlements (Category 8)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class ChannelSyncLog(Base, TimestampMixin):
    """Append-only record of menu/stock/pause pushes to marketplaces."""

    __tablename__ = "channel_sync_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    detail: Mapped[str | None] = mapped_column(Text)
    items_touched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class ChannelSettlement(Base, TimestampMixin):
    """Imported or recorded marketplace settlement for recon vs internal totals."""

    __tablename__ = "channel_settlements"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id",
            "provider",
            "period_start",
            "period_end",
            name="uq_channel_settlements_period",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    order_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    gross_revenue_aed: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), server_default="0"
    )
    commission_aed: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), server_default="0"
    )
    net_aed: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), default=Decimal("0.00"), server_default="0"
    )
    status: Mapped[str] = mapped_column(
        String(24), default="recorded", server_default="recorded"
    )
    external_ref: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(Text)
