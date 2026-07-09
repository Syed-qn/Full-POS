"""UAE compliance artifacts: refund notes, e-invoice transmissions, retention runs."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class RefundNote(Base, TimestampMixin):
    """Formal refund-note document (distinct from credit notes / payment refunds)."""

    __tablename__ = "refund_notes"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id",
            "refund_note_number",
            name="uq_refund_notes_restaurant_number",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("payment_transactions.id"), index=True
    )
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    vat_amount_aed: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0"
    )
    reason: Mapped[str | None] = mapped_column(String(256))
    refund_note_number: Mapped[str] = mapped_column(String(32), index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EInvoiceTransmission(Base, TimestampMixin):
    """E-invoicing ASP transmission log (mock ASP ready for real provider)."""

    __tablename__ = "e_invoice_transmissions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="queued", server_default="queued")
    asp_provider: Mapped[str] = mapped_column(String(64), default="mock", server_default="mock")
    external_id: Mapped[str | None] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    response: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    error: Mapped[str | None] = mapped_column(Text)
    transmitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DataRetentionRun(Base, TimestampMixin):
    __tablename__ = "data_retention_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    retention_days: Mapped[int] = mapped_column(Integer)
    purged_counts: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(String(16), default="completed", server_default="completed")
    notes: Mapped[str | None] = mapped_column(Text)
