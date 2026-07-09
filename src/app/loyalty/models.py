"""Loyalty models — referral codes and NPS survey responses.

Both are NEW, non-overlapping additions to the existing tier/earn loyalty
system in ``app.loyalty.service`` (which lives entirely on ``Customer``
columns + the wallet ledger). Neither table duplicates that system.
"""
from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class ReferralCode(Base, TimestampMixin):
    """A customer's shareable referral code. One owner per code; codes are
    unique per tenant (two restaurants may both mint "AB12CD")."""

    __tablename__ = "referral_codes"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "code", name="uq_referral_codes_restaurant_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    code: Mapped[str] = mapped_column(String(16), index=True)


class NpsResponse(Base, TimestampMixin):
    """One Net Promoter Score survey response tied to a delivered order."""

    __tablename__ = "nps_responses"
    __table_args__ = (
        Index("ix_nps_responses_restaurant_created_at", "restaurant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    score: Mapped[int] = mapped_column(SmallInteger)
    comment: Mapped[str | None] = mapped_column(Text)


class StampCard(Base, TimestampMixin):
    """Per-customer digital stamp card (earn on delivery, redeem for reward)."""

    __tablename__ = "stamp_cards"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "customer_id", name="uq_stamp_cards_restaurant_customer"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    stamps: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rewards_redeemed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Stamps needed for one reward (copied from settings at last earn; default 10).
    stamps_required: Mapped[int] = mapped_column(Integer, default=10, server_default="10")


class LoyaltyPointEntry(Base, TimestampMixin):
    """Append-only loyalty points ledger (parallel to wallet AED cashback)."""

    __tablename__ = "loyalty_point_entries"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_loyalty_point_entries_idem"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    points: Mapped[int] = mapped_column(Integer)  # signed: +earn / -redeem
    reason: Mapped[str] = mapped_column(String(64))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
