from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class PaymentTransaction(Base, TimestampMixin):
    """One tender against an order. Multiple rows per order = split payment."""

    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    tender_type: Mapped[str] = mapped_column(String(16))  # cash | card | apple_pay | google_pay | wallet | deposit
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    tip_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    provider: Mapped[str] = mapped_column(String(16), default="mock")
    provider_charge_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), default="pending")  # pending|succeeded|failed|refunded|partially_refunded
    refunded_amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))


class CreditNote(Base, TimestampMixin):
    """Formal credit note artifact issued against a refunded PaymentTransaction.

    ``credit_note_number`` is allocated the same way as ``Order.order_number``
    (see ``create_draft_order`` in app.ordering.service): a per-tenant advisory
    lock + max-existing-suffix scan + SAVEPOINT retry on collision, never a
    racy ``count() + 1``.
    """

    __tablename__ = "credit_notes"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "credit_note_number", name="uq_credit_notes_restaurant_number"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("payment_transactions.id"), index=True)
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    reason: Mapped[str | None] = mapped_column(String(256))
    credit_note_number: Mapped[str] = mapped_column(String(32), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
