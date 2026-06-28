"""Wallet ledger models (financial-grade, append-only).

Design (see docs/research/wallet-coupon-financial-design.md):
- One ``WalletAccount`` per (restaurant, customer). Identity only — NO balance
  column. The balance is DERIVED by summing ``WalletEntry`` rows.
- ``WalletEntry`` is an append-only journal. A correction is a reversing entry,
  never an edit/delete. Every value movement carries a unique ``idempotency_key``
  so replays (retry, webhook redelivery, double-click) never double-apply.
- A spend is modelled hold -> capture/release (bank authorize/capture): a hold is
  a negative ``held`` entry that reduces *available* but not *balance*; capture
  flips it to a posted ``order_debit``; release returns the credit.
"""
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class WalletAccount(Base, TimestampMixin):
    """One wallet per (restaurant, customer). Identity only — balance is derived
    by summing :class:`WalletEntry` rows, never stored here."""

    __tablename__ = "wallet_accounts"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "customer_id", name="uq_wallet_accounts_restaurant_customer"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    # active | frozen  (frozen = abuse hold; spend blocked)
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)


class WalletEntry(Base, TimestampMixin):
    """Append-only ledger row.

    ``balance``   = SUM(amount_aed WHERE status='posted')
    ``available`` = balance + SUM(amount_aed WHERE status='held')   (holds are negative)
    """

    __tablename__ = "wallet_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_wallet_entries_idempotency_key"),
        Index("ix_wallet_entries_account_status", "account_id", "status"),
        Index("ix_wallet_entries_order", "account_id", "order_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("wallet_accounts.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    # +credit / -debit. AED, two decimals, never float.
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    # refund_credit | promo_credit | order_debit | hold | hold_release |
    # manual_adjust | expiry | reversal
    type: Mapped[str] = mapped_column(String(24), index=True)
    # posted | held
    status: Mapped[str] = mapped_column(String(8), default="posted", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    ticket_id: Mapped[int | None] = mapped_column(BigInteger)
    order_id: Mapped[int | None] = mapped_column(BigInteger)
    reverses_entry_id: Mapped[int | None] = mapped_column(BigInteger)
    reason_note: Mapped[str | None] = mapped_column(String(512))
    created_by: Mapped[str] = mapped_column(String(64))
