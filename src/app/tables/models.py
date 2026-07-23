from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class DiningTable(Base, TimestampMixin):
    __tablename__ = "tables"
    __table_args__ = (UniqueConstraint("qr_token", name="uq_tables_qr_token"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    label: Mapped[str] = mapped_column(String(32))
    seats: Mapped[int] = mapped_column(Integer, default=2)
    pos_x: Mapped[float] = mapped_column(Float, default=0.0)
    pos_y: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="available")
    # Degrees clockwise. A real room has tables at angles — a banquette along a
    # diagonal wall, a bar-end two-top — so the plan must be able to say so.
    rotation: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # Opaque token for QR-table ordering links (public order create).
    qr_token: Mapped[str | None] = mapped_column(String(64), index=True)
    # Soft delete. Orders keep a FK to their table, so a table a guest ever sat
    # at can never be hard-deleted without destroying order history — removing
    # a table from the floor archives it and every read filters it out.
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
