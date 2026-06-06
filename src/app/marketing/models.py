from sqlalchemy import BigInteger, ForeignKey, String, UniqueConstraint
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
