from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class SlaEvent(Base, TimestampMixin):
    """Records yellow/red/breach SLA alerts for an order."""

    __tablename__ = "sla_events"
    __table_args__ = (UniqueConstraint("order_id", "type", name="uq_sla_events_order_type"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    # yellow_30 | red_35 | breach_40
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    notified: Mapped[dict] = mapped_column(JSONB, default=dict)
    # {"customer": bool, "manager": bool}
