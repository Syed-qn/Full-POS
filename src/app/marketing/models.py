from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
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


class MarketingMedia(Base):
    """Header-image bytes for marketing templates, stored in Postgres so they
    survive redeploys on ephemeral-disk hosts (Render free tier wipes local
    disk on every deploy). Keyed by the relative media path so the existing
    ``/media/<path>`` URL scheme is unchanged. Write-once (no updated_at, so no
    trigger needed); a re-upload writes a fresh row under a new uuid path.
    """

    __tablename__ = "marketing_media"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    path: Mapped[str] = mapped_column(String(256), unique=True)
    content_type: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
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


class MarketingAutomation(Base, TimestampMixin):
    """Preset marketing automation (welcome, winback, reorder, recurring)."""

    __tablename__ = "marketing_automations"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "preset_key", name="uq_marketing_automation_preset"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    preset_key: Mapped[str] = mapped_column(String(16))
    enabled: Mapped[bool] = mapped_column(default=False)
    template_id: Mapped[int | None] = mapped_column(
        ForeignKey("wa_templates.id"), nullable=True
    )
    segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("segments.id"), nullable=True
    )
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    stats: Mapped[dict] = mapped_column(JSONB, default=dict)
    last_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RecurringMessageState(Base, TimestampMixin):
    """Per-customer recurring promo schedule (day3 → weekly)."""

    __tablename__ = "recurring_message_state"
    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "customer_id", name="uq_recurring_message_customer"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), index=True
    )
    next_send_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    suppressed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    phase: Mapped[str] = mapped_column(String(8), default="day3")
    weekday: Mapped[int] = mapped_column(default=0)
    usual_send_local_time: Mapped[str] = mapped_column(String(5), default="11:45")


class MarketingAutomationSend(Base):
    """Dedup ledger — one welcome per customer; winback uses time-window checks."""

    __tablename__ = "marketing_automation_sends"
    __table_args__ = (
        UniqueConstraint(
            "automation_id", "customer_id", name="uq_marketing_automation_send"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    automation_id: Mapped[int] = mapped_column(
        ForeignKey("marketing_automations.id"), index=True
    )
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("customers.id"), index=True
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id"), nullable=True
    )


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
