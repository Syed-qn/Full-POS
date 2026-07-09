"""Persisted AI artifacts (Cat 14)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class AiInsight(Base, TimestampMixin):
    """Generated AI insight (daily sales, sales drop, staff summary, etc.)."""

    __tablename__ = "ai_insights"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    kind: Mapped[str] = mapped_column(String(48), index=True)
    title: Mapped[str] = mapped_column(String(256))
    summary: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)


class ReviewReplySuggestion(Base, TimestampMixin):
    __tablename__ = "review_reply_suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    nps_response_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    customer_id: Mapped[int | None] = mapped_column(BigInteger)
    score: Mapped[int | None] = mapped_column(Integer)
    original_comment: Mapped[str | None] = mapped_column(Text)
    suggested_reply: Mapped[str] = mapped_column(Text)
    sentiment: Mapped[str] = mapped_column(String(24), default="neutral", server_default="neutral")
    escalated: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    ticket_id: Mapped[int | None] = mapped_column(BigInteger)


class ReservationRequest(Base, TimestampMixin):
    __tablename__ = "reservation_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int | None] = mapped_column(BigInteger)
    phone: Mapped[str | None] = mapped_column(String(32))
    guest_name: Mapped[str | None] = mapped_column(String(128))
    party_size: Mapped[int] = mapped_column(Integer, default=2, server_default="2")
    requested_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(24), default="pending", server_default="pending")
    table_id: Mapped[int | None] = mapped_column(BigInteger)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(32), default="dashboard", server_default="dashboard")


class CallAnswerSession(Base, TimestampMixin):
    """AI phone / IVR-style order-taking session (mock telephony ready)."""

    __tablename__ = "call_answer_sessions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    caller_phone: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(24), default="active", server_default="active")
    transcript: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    ai_summary: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(48))
    order_id: Mapped[int | None] = mapped_column(BigInteger)


class MenuTranslation(Base, TimestampMixin):
    __tablename__ = "menu_translations"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id",
            "dish_id",
            "target_lang",
            name="uq_menu_translations_dish_lang",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"), index=True)
    source_lang: Mapped[str] = mapped_column(String(8), default="en", server_default="en")
    target_lang: Mapped[str] = mapped_column(String(8), default="ar", server_default="ar")
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
