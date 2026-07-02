"""Queue table for outbound webhooks to partner POS systems."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class PartnerWebhookDelivery(Base, TimestampMixin):
    """One outbound POST to a partner's webhook URL.

    Written in the same DB transaction as the business event (order confirm, etc.),
    then delivered asynchronously by a Celery worker with retry + dead-letter.
    Separate from ``outbox_messages`` (WhatsApp phone sends).
    """

    __tablename__ = "partner_webhook_deliveries"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    target_url: Mapped[str] = mapped_column(String(512))
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )