from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class GiftCard(Base, TimestampMixin):
    """Physical/digital gift card with code + PIN, independent of wallet phone credit."""

    __tablename__ = "gift_cards"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "code", name="uq_gift_cards_restaurant_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), index=True)
    pin_hash: Mapped[str] = mapped_column(String(128))
    initial_amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    balance_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    # active | void | exhausted
    status: Mapped[str] = mapped_column(String(16), default="active", server_default="active")
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_by: Mapped[str] = mapped_column(String(64), default="manager")
