from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin

# Gateway (PSP / terminal) tenders
GATEWAY_TENDERS = frozenset({"card", "apple_pay", "google_pay", "tap_to_pay", "online"})
# Settled locally without external PSP call
LOCAL_TENDERS = frozenset(
    {
        "cash",
        "wallet",
        "deposit",
        "pay_later",
        "room_charge",
        "gift_card",
        "house_account",
    }
)
ALL_TENDERS = GATEWAY_TENDERS | LOCAL_TENDERS


class PaymentTransaction(Base, TimestampMixin):
    """One tender against an order. Multiple rows per order = split payment."""

    __tablename__ = "payment_transactions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    # cash|card|apple_pay|google_pay|wallet|deposit|tap_to_pay|online|pay_later|room_charge|gift_card|house_account
    tender_type: Mapped[str] = mapped_column(String(24))
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    tip_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    provider: Mapped[str] = mapped_column(String(16), default="mock")
    provider_charge_id: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(24), default="pending"
    )  # pending|succeeded|failed|refunded|partially_refunded
    refunded_amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    # till | online | payment_link | terminal
    channel: Mapped[str] = mapped_column(String(24), default="till", server_default="till")
    # room number, terminal id, wallet session, gift card code, etc.
    reference_meta: Mapped[str | None] = mapped_column(String(256))
    wallet_session_id: Mapped[str | None] = mapped_column(String(128))


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


class PaymentLink(Base, TimestampMixin):
    """Shareable online payment link for an order (WhatsApp / SMS / email)."""

    __tablename__ = "payment_links"
    __table_args__ = (
        UniqueConstraint("token", name="uq_payment_links_token"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    token: Mapped[str] = mapped_column(String(64), index=True)
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    # pending | paid | expired | cancelled
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    paid_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_transactions.id"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(64), default="manager")


class PaymentSettlement(Base, TimestampMixin):
    """PSP payout / settlement batch for reconciliation against charge ledger."""

    __tablename__ = "payment_settlements"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(16), default="stripe")
    provider_payout_id: Mapped[str] = mapped_column(String(128), index=True)
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    currency: Mapped[str] = mapped_column(String(8), default="AED")
    settled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # open | matched | partial | unmatched
    status: Mapped[str] = mapped_column(String(16), default="open", server_default="open")
    matched_txn_count: Mapped[int] = mapped_column(default=0, server_default="0")
    notes: Mapped[str | None] = mapped_column(String(256))


class PaymentSettlementLine(Base, TimestampMixin):
    __tablename__ = "payment_settlement_lines"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    settlement_id: Mapped[int] = mapped_column(ForeignKey("payment_settlements.id"), index=True)
    provider_charge_id: Mapped[str] = mapped_column(String(128), index=True)
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    payment_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_transactions.id"), nullable=True
    )
    # matched | unmatched | amount_mismatch
    match_status: Mapped[str] = mapped_column(String(24), default="unmatched")
