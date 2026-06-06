from sqlalchemy import BigInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base, TimestampMixin


class WebhookEvent(Base, TimestampMixin):
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider_event_id: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    processed_at: Mapped[str | None] = mapped_column(String(64))
