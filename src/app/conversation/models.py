from sqlalchemy import BigInteger, Boolean, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    counterpart: Mapped[str] = mapped_column(String(16))
    phone: Mapped[str] = mapped_column(String(32), index=True)
    state: Mapped[dict] = mapped_column(JSONB, default=dict)
    manual_takeover: Mapped[bool] = mapped_column(Boolean, default=False)
    taken_over_by: Mapped[int | None] = mapped_column(BigInteger)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    wa_message_id: Mapped[str | None] = mapped_column(String(256), index=True)
    type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB)
    ts: Mapped[int] = mapped_column(BigInteger, default=0)  # unix epoch — BigInteger avoids 2038 overflow
    # Inbound WhatsApp attachments (voice, image, PDF, video): persisted at receive
    # time so managers can view them in the dashboard after Meta media ids expire.
    media_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    media_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
