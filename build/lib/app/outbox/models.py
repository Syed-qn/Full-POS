from sqlalchemy import BigInteger, ForeignKey, Integer, String
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
