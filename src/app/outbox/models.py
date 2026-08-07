from sqlalchemy import BigInteger, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base, TimestampMixin


class OutboxMessage(Base, TimestampMixin):
    __tablename__ = "outbox_messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    to_phone: Mapped[str] = mapped_column(String(32), index=True)
    payload: Mapped[dict] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    wa_message_id: Mapped[str | None] = mapped_column(String(256))
    idempotency_key: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    # Why the last send attempt failed, straight from the provider. Without it a
    # 'failed' row says nothing and the only way to learn the cause is to replay the
    # Graph call by hand — which is exactly what a broken catalogue card cost us.
    # Cleared on success so a recovered row never shows a stale reason.
    last_error: Mapped[str | None] = mapped_column(Text)
