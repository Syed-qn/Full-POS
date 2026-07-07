from decimal import Decimal

from sqlalchemy import BigInteger, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class PaymentTransaction(Base, TimestampMixin):
    """One tender against an order. Multiple rows per order = split payment."""

    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    tender_type: Mapped[str] = mapped_column(String(16))  # cash | card | apple_pay | google_pay | wallet
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    tip_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    provider: Mapped[str] = mapped_column(String(16), default="mock")
    provider_charge_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|succeeded|failed|refunded|partially_refunded
    refunded_amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
