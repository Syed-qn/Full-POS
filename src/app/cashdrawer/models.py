from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class CashDrawerSession(Base, TimestampMixin):
    __tablename__ = "cash_drawer_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    opened_by: Mapped[str] = mapped_column(String(64))
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    opening_float_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    closed_by: Mapped[str | None] = mapped_column(String(64))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closing_count_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    variance_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(16), default="open")


class CashDrawerEvent(Base, TimestampMixin):
    __tablename__ = "cash_drawer_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("cash_drawer_sessions.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # cash_in | cash_out
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    reason: Mapped[str | None] = mapped_column(String(256))
    created_by: Mapped[str] = mapped_column(String(64))
