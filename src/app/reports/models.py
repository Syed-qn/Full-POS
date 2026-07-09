"""Persisted owner-report delivery log (Category 10)."""

from datetime import date

from sqlalchemy import BigInteger, Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class OwnerReportDelivery(Base, TimestampMixin):
    __tablename__ = "owner_report_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    to_phone: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="sent")  # sent | failed
    body_preview: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
