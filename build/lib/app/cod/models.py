from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class CodCollection(Base, TimestampMixin):
    """Records cash collected by a rider for a delivered order."""

    __tablename__ = "cod_collections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True, index=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RiderShiftReconciliation(Base, TimestampMixin):
    """End-of-shift COD cash reconciliation for a rider."""

    __tablename__ = "rider_shift_reconciliations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rider_id: Mapped[int] = mapped_column(ForeignKey("riders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    shift_date: Mapped[datetime] = mapped_column(Date, index=True)
    expected_total_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    collected_total_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    variance_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    # pending | balanced | variance
