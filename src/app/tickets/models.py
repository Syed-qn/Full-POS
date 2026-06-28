"""Complaint ticket model.

A complaint is HUMAN-handled only: the AI may open a ticket + acknowledge, but
every resolution is a manager action (refund-to-wallet / replacement / mark
resolved). See docs/research/complaint-ticket-system-design.md.
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class Ticket(Base, TimestampMixin):
    __tablename__ = "tickets"
    __table_args__ = (
        Index("ix_tickets_restaurant_status", "restaurant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)

    source_message: Mapped[str | None] = mapped_column(Text)
    # list of {kind, url|transcript} captured from the inbound complaint
    evidence: Mapped[list] = mapped_column(JSONB, default=list)
    # quality | missing | wrong | delivery | rider | payment | safety | other
    category: Mapped[str | None] = mapped_column(String(16))

    # open | in_progress | resolved
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    assigned_to: Mapped[str | None] = mapped_column(String(64))

    # none | wallet_refund | replacement | resolved_no_action
    resolution_action: Mapped[str] = mapped_column(String(24), default="none")
    resolution_amount_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    replacement_order_id: Mapped[int | None] = mapped_column(BigInteger)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
