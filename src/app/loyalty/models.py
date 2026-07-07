"""Loyalty models — referral codes and NPS survey responses.

Both are NEW, non-overlapping additions to the existing tier/earn loyalty
system in ``app.loyalty.service`` (which lives entirely on ``Customer``
columns + the wallet ledger). Neither table duplicates that system.
"""
from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Index,
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
