from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class StaffMember(Base, TimestampMixin):
    __tablename__ = "staff_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(32), default="staff")
    pin_hash: Mapped[str] = mapped_column(String(256))


class ClockEvent(Base, TimestampMixin):
    __tablename__ = "clock_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_members.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # clock_in | clock_out
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
