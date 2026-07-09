from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class StaffMember(Base, TimestampMixin):
    __tablename__ = "staff_members"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    role: Mapped[str] = mapped_column(String(32), default="staff")
    pin_hash: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Training mode: orders attributed to this staff are flagged is_training
    # and excluded from real sales/performance KPIs.
    training_mode: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )


class ClockEvent(Base, TimestampMixin):
    __tablename__ = "clock_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_members.id"), index=True)
    type: Mapped[str] = mapped_column(String(16))  # clock_in | clock_out | break_start | break_end
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApprovalRequest(Base, TimestampMixin):
    """Manager PIN approval queue for void / discount / refund overrides."""

    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    action_type: Mapped[str] = mapped_column(String(32))  # void|discount|refund|manager_override
    status: Mapped[str] = mapped_column(String(16), default="pending", server_default="pending")
    requested_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_members.id"))
    approved_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_members.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    amount_aed: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    reason: Mapped[str | None] = mapped_column(String(256))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StaffMistake(Base, TimestampMixin):
    """Operational mistakes (wrong item, spill, void after cook, etc.)."""

    __tablename__ = "staff_mistakes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff_members.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    mistake_type: Mapped[str] = mapped_column(String(32))
    amount_aed: Mapped[Decimal] = mapped_column(
        Numeric(8, 2), default=Decimal("0.00"), server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(String(512))


class SuspiciousActivityAlert(Base, TimestampMixin):
    __tablename__ = "suspicious_activity_alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    alert_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16), default="medium", server_default="medium")
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff_members.id"))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
