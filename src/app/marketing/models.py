from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class OptOut(Base, TimestampMixin):
    """A customer (by phone) who has opted out of marketing for a restaurant.

    Idempotent per (restaurant_id, phone) — the unique constraint backs the
    ON CONFLICT DO NOTHING upsert in ``optout.record_opt_out``.
    """

    __tablename__ = "marketing_opt_outs"
    __table_args__ = (UniqueConstraint("restaurant_id", "phone"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    phone: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(32), default="stop_keyword")


class WaTemplate(Base, TimestampMixin):
    """A WhatsApp message template registered with Meta for marketing.

    ``meta_template_name`` is the datestamped, ``^[a-z0-9_]+$`` slug produced by
    ``naming.datestamped_name``; uniqueness is per (restaurant, name, language).
    """

    __tablename__ = "wa_templates"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "meta_template_name", "language",
            name="uq_wa_template_name_lang",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    meta_template_name: Mapped[str] = mapped_column(String(512))
    language: Mapped[str] = mapped_column(String(8), default="en")
    category: Mapped[str] = mapped_column(String(16), default="marketing")
    header: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    body: Mapped[str] = mapped_column(Text)
    footer: Mapped[str | None] = mapped_column(String(60), nullable=True)
    buttons: Mapped[list] = mapped_column(JSONB, default=list)
    # draft|pending_meta|approved|rejected|paused|disabled|sent|deleted
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    ephemeral: Mapped[bool] = mapped_column(default=True)
    meta_template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class Segment(Base, TimestampMixin):
    """A saved audience segment defined by a validated DSL definition."""

    __tablename__ = "segments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(128))
    plain_english: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition: Mapped[dict] = mapped_column(JSONB)
    last_preview_count: Mapped[int | None] = mapped_column(nullable=True)


class Campaign(Base, TimestampMixin):
    """A marketing send job: a template + segment dispatched to recipients."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    type: Mapped[str] = mapped_column(String(16))  # todays_special|recurring|automation
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("wa_templates.id"), nullable=True
    )
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("segments.id"), nullable=True
    )
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    coupon_value: Mapped[str | None] = mapped_column(String(16), nullable=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # draft|scheduled|sending|sent|failed|cancelled
    status: Mapped[str] = mapped_column(String(16), default="draft", index=True)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)


class MarketingSend(Base, TimestampMixin):
    """Per-recipient send ledger — backs the 24h frequency cap and analytics.

    Unique per (campaign, customer) so a recipient is never double-sent within
    one campaign; ``(to_phone, sent_at)`` index serves the 24h cap lookups.
    """

    __tablename__ = "marketing_sends"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id", "customer_id",
            name="uq_marketing_send_campaign_customer",
        ),
        Index("ix_marketing_sends_phone_sent", "to_phone", "sent_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), index=True
    )
    to_phone: Mapped[str] = mapped_column(String(32), index=True)
    # queued|sent|delivered|read|failed|suppressed_cap|suppressed_optout|suppressed_window
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    wa_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[int | None] = mapped_column(nullable=True)  # e.g. 131049
    converted_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id"), nullable=True
    )  # attribution
    sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
