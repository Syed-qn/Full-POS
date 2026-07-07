# src/app/idempotency/models.py
from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class IdempotencyKey(Base, TimestampMixin):
    """Dedup record for a replayed mutating request.

    Scoped by (restaurant_id, key, method, path): a retried desktop-shell sync
    op after a dropped connection replays the exact same call and must get back
    the original response, never re-apply the mutation. The unique index is the
    actual dedup guarantee under concurrent retries; the middleware's SELECT is
    just the fast path.
    """

    __tablename__ = "idempotency_keys"
    __table_args__ = (
        Index(
            "ux_idempotency_keys_restaurant_key_method_path",
            "restaurant_id",
            "key",
            "method",
            "path",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(
        ForeignKey("restaurants.id"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    path: Mapped[str] = mapped_column(String(255), nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[str] = mapped_column(Text, nullable=False)
