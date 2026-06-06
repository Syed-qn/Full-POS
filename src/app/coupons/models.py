from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Coupon(Base, TimestampMixin):
    """Late-delivery apology coupon. Single-use, issued per order breach."""

    __tablename__ = "coupons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    # cause — the order that triggered this coupon
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    discount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    status: Mapped[str] = mapped_column(String(16), default="issued", index=True)
    # issued | redeemed | expired
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    redeemed_on_order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
