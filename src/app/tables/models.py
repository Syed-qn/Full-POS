from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String, UniqueConstraint
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
    # Opaque token for QR-table ordering links (public order create).
    qr_token: Mapped[str | None] = mapped_column(String(64), index=True)
