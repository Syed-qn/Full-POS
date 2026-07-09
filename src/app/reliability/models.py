"""Category 12 — backups, devices, error logs, DR snapshots."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, TimestampMixin


class BackupJob(Base, TimestampMixin):
    """Record of a tenant backup (cloud snapshot written to disk/object path)."""

    __tablename__ = "backup_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    # manual | daily | cloud | pre_restore
    kind: Mapped[str] = mapped_column(String(24), default="manual")
    # pending | running | completed | failed
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    storage_path: Mapped[str | None] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    checksum: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeviceRegistration(Base, TimestampMixin):
    """POS terminal / KDS device registry for multi-device sync + failover."""

    __tablename__ = "device_registrations"
    __table_args__ = (
        UniqueConstraint("restaurant_id", "device_id", name="uq_device_restaurant"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    device_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    # pos | kds | printer | backup_terminal
    device_type: Mapped[str] = mapped_column(String(24), default="pos")
    # primary | standby | offline
    role: Mapped[str] = mapped_column(String(16), default="primary")
    status: Mapped[str] = mapped_column(String(16), default="online")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_failover_active: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class AppErrorLog(Base, TimestampMixin):
    """In-app error log viewer (complements optional Sentry)."""

    __tablename__ = "app_error_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int | None] = mapped_column(
        ForeignKey("restaurants.id"), index=True
    )
    level: Mapped[str] = mapped_column(String(16), default="error")  # error|warn|info
    source: Mapped[str] = mapped_column(String(64), default="api")
    message: Mapped[str] = mapped_column(String(512))
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class OfflinePaymentLedger(Base, TimestampMixin):
    """Server-side acceptance of offline-collected payments once device syncs."""

    __tablename__ = "offline_payment_ledger"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    client_payment_id: Mapped[str] = mapped_column(String(64), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    amount_aed: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    tender_type: Mapped[str] = mapped_column(String(24), default="cash")
    # queued | applied | rejected
    status: Mapped[str] = mapped_column(String(16), default="applied")
    device_id: Mapped[str | None] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")


class DrDrillLog(Base, TimestampMixin):
    """Disaster-recovery drill / restore attempt log."""

    __tablename__ = "dr_drill_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), index=True)
    backup_job_id: Mapped[int | None] = mapped_column(ForeignKey("backup_jobs.id"))
    # drill | restore | verify
    kind: Mapped[str] = mapped_column(String(16), default="drill")
    status: Mapped[str] = mapped_column(String(16), default="ok")
    notes: Mapped[str | None] = mapped_column(Text)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, server_default="{}")
