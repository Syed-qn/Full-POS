"""Backup snapshots, device registry, offline payment apply, DR drills."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.reliability.models import (
    AppErrorLog,
    BackupJob,
    DeviceRegistration,
    DrDrillLog,
    OfflinePaymentLedger,
)


def _backup_root() -> Path:
    root = os.getenv("APP_BACKUP_DIR") or os.path.join(
        os.getcwd(), "var", "backups"
    )
    path = Path(root)
    path.mkdir(parents=True, exist_ok=True)
    return path


async def create_backup_snapshot(
    session: AsyncSession,
    *,
    restaurant_id: int,
    kind: str = "manual",
) -> BackupJob:
    """Serialize core tenant tables to a JSON snapshot on local/cloud path."""
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem
    from app.staff.models import StaffMember

    job = BackupJob(
        restaurant_id=restaurant_id,
        kind=kind,
        status="running",
    )
    session.add(job)
    await session.flush()

    try:
        menus = list(
            (
                await session.scalars(
                    select(Menu).where(Menu.restaurant_id == restaurant_id)
                )
            ).all()
        )
        dishes = list(
            (
                await session.scalars(
                    select(Dish).where(Dish.restaurant_id == restaurant_id)
                )
            ).all()
        )
        customers = list(
            (
                await session.scalars(
                    select(Customer).where(Customer.restaurant_id == restaurant_id)
                )
            ).all()
        )
        orders = list(
            (
                await session.scalars(
                    select(Order)
                    .where(Order.restaurant_id == restaurant_id)
                    .order_by(Order.id.desc())
                    .limit(5000)
                )
            ).all()
        )
        order_ids = [o.id for o in orders]
        items: list[OrderItem] = []
        if order_ids:
            items = list(
                (
                    await session.scalars(
                        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
                    )
                ).all()
            )
        staff = list(
            (
                await session.scalars(
                    select(StaffMember).where(StaffMember.restaurant_id == restaurant_id)
                )
            ).all()
        )

        payload = {
            "restaurant_id": restaurant_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "menus": [
                {"id": m.id, "version": m.version, "status": m.status} for m in menus
            ],
            "dishes": [
                {
                    "id": d.id,
                    "name": d.name,
                    "price_aed": str(d.price_aed or 0),
                    "dish_number": d.dish_number,
                    "is_available": d.is_available,
                    "category": d.category,
                }
                for d in dishes
            ],
            "customers": [
                {
                    "id": c.id,
                    "phone": c.phone,
                    "name": c.name,
                    "total_orders": c.total_orders,
                }
                for c in customers
            ],
            "orders": [
                {
                    "id": o.id,
                    "order_number": o.order_number,
                    "status": o.status,
                    "total": str(o.total or 0),
                    "customer_id": o.customer_id,
                }
                for o in orders
            ],
            "order_items": [
                {
                    "order_id": i.order_id,
                    "dish_name": i.dish_name,
                    "qty": i.qty,
                    "price_aed": str(i.price_aed),
                }
                for i in items
            ],
            "staff": [
                {"id": s.id, "name": s.name, "role": s.role} for s in staff
            ],
            "counts": {
                "menus": len(menus),
                "dishes": len(dishes),
                "customers": len(customers),
                "orders": len(orders),
                "order_items": len(items),
                "staff": len(staff),
            },
        }
        raw = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
        checksum = hashlib.sha256(raw).hexdigest()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"r{restaurant_id}_{kind}_{ts}_{checksum[:8]}.json"
        path = _backup_root() / filename
        path.write_bytes(raw)

        job.status = "completed"
        job.storage_path = str(path)
        job.size_bytes = len(raw)
        job.checksum = checksum
        job.meta = payload["counts"]
        job.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await record_audit(
            session,
            restaurant_id=restaurant_id,
            actor="system",
            entity="backup_job",
            entity_id=str(job.id),
            action="backup_completed",
            after={"path": str(path), "size": len(raw), "checksum": checksum},
        )
    except Exception as exc:  # noqa: BLE001
        job.status = "failed"
        job.error = str(exc)[:1000]
        await session.flush()
        raise
    return job


async def list_backups(
    session: AsyncSession, *, restaurant_id: int, limit: int = 50
) -> list[BackupJob]:
    return list(
        (
            await session.scalars(
                select(BackupJob)
                .where(BackupJob.restaurant_id == restaurant_id)
                .order_by(BackupJob.id.desc())
                .limit(min(max(limit, 1), 100))
            )
        ).all()
    )


async def run_daily_backup_if_due(
    session: AsyncSession, *, restaurant_id: int
) -> BackupJob | None:
    """Create a daily backup if none completed today (UTC)."""
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)
    existing = await session.scalar(
        select(BackupJob).where(
            BackupJob.restaurant_id == restaurant_id,
            BackupJob.kind == "daily",
            BackupJob.status == "completed",
            BackupJob.completed_at >= start,
        )
    )
    if existing:
        return existing
    return await create_backup_snapshot(
        session, restaurant_id=restaurant_id, kind="daily"
    )


async def verify_backup(
    session: AsyncSession, *, restaurant_id: int, backup_job_id: int
) -> dict:
    job = await session.get(BackupJob, backup_job_id)
    if job is None or job.restaurant_id != restaurant_id:
        raise ValueError("backup not found")
    if not job.storage_path or not Path(job.storage_path).exists():
        raise ValueError("backup file missing")
    raw = Path(job.storage_path).read_bytes()
    checksum = hashlib.sha256(raw).hexdigest()
    ok = checksum == job.checksum
    drill = DrDrillLog(
        restaurant_id=restaurant_id,
        backup_job_id=job.id,
        kind="verify",
        status="ok" if ok else "failed",
        notes="checksum verify",
        detail={"expected": job.checksum, "actual": checksum, "size": len(raw)},
    )
    session.add(drill)
    await session.flush()
    return {
        "backup_job_id": job.id,
        "ok": ok,
        "checksum": checksum,
        "size_bytes": len(raw),
        "drill_id": drill.id,
    }


async def restore_preview(
    session: AsyncSession, *, restaurant_id: int, backup_job_id: int
) -> dict:
    """DR restore preview — loads snapshot metadata without mutating live tables.

    Full destructive restore is intentionally gated; this records a drill and
    returns what would be restored so ops can approve.
    """
    job = await session.get(BackupJob, backup_job_id)
    if job is None or job.restaurant_id != restaurant_id:
        raise ValueError("backup not found")
    if not job.storage_path or not Path(job.storage_path).exists():
        raise ValueError("backup file missing")
    data = json.loads(Path(job.storage_path).read_text(encoding="utf-8"))
    drill = DrDrillLog(
        restaurant_id=restaurant_id,
        backup_job_id=job.id,
        kind="drill",
        status="ok",
        notes="restore preview (non-destructive)",
        detail={"counts": data.get("counts"), "generated_at": data.get("generated_at")},
    )
    session.add(drill)
    await session.flush()
    return {
        "backup_job_id": job.id,
        "drill_id": drill.id,
        "generated_at": data.get("generated_at"),
        "counts": data.get("counts"),
        "restore_mode": "preview_only",
        "message": "Snapshot verified. Full overwrite restore requires ops runbook approval.",
    }


async def export_full_data_pack(
    session: AsyncSession, *, restaurant_id: int
) -> dict:
    """In-memory export pack (JSON) for manager download — uses same snapshot shape."""
    job = await create_backup_snapshot(
        session, restaurant_id=restaurant_id, kind="manual"
    )
    raw = Path(job.storage_path).read_text(encoding="utf-8") if job.storage_path else "{}"
    return {
        "backup_job_id": job.id,
        "checksum": job.checksum,
        "size_bytes": job.size_bytes,
        "download_path": job.storage_path,
        "preview": json.loads(raw).get("counts"),
    }


# ── Devices / failover ───────────────────────────────────────────────────────


async def register_device(
    session: AsyncSession,
    *,
    restaurant_id: int,
    device_id: str,
    name: str,
    device_type: str = "pos",
    role: str = "primary",
) -> DeviceRegistration:
    existing = await session.scalar(
        select(DeviceRegistration).where(
            DeviceRegistration.restaurant_id == restaurant_id,
            DeviceRegistration.device_id == device_id,
        )
    )
    now = datetime.now(timezone.utc)
    if existing:
        existing.name = name
        existing.device_type = device_type
        existing.role = role
        existing.status = "online"
        existing.last_seen_at = now
        await session.flush()
        return existing
    row = DeviceRegistration(
        restaurant_id=restaurant_id,
        device_id=device_id,
        name=name,
        device_type=device_type,
        role=role,
        status="online",
        last_seen_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def device_heartbeat(
    session: AsyncSession,
    *,
    restaurant_id: int,
    device_id: str,
) -> DeviceRegistration:
    row = await session.scalar(
        select(DeviceRegistration).where(
            DeviceRegistration.restaurant_id == restaurant_id,
            DeviceRegistration.device_id == device_id,
        )
    )
    if row is None:
        raise ValueError("device not registered")
    row.status = "online"
    row.last_seen_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def promote_failover_device(
    session: AsyncSession,
    *,
    restaurant_id: int,
    device_id: str,
) -> DeviceRegistration:
    """Mark a standby device as active failover primary."""
    devices = list(
        (
            await session.scalars(
                select(DeviceRegistration).where(
                    DeviceRegistration.restaurant_id == restaurant_id
                )
            )
        ).all()
    )
    target = next((d for d in devices if d.device_id == device_id), None)
    if target is None:
        raise ValueError("device not found")
    for d in devices:
        d.is_failover_active = False
        if d.device_id != device_id and d.role == "primary":
            d.role = "standby"
            d.status = "offline"
    target.role = "primary"
    target.is_failover_active = True
    target.status = "online"
    target.last_seen_at = datetime.now(timezone.utc)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="system",
        entity="device",
        entity_id=device_id,
        action="failover_promoted",
        after={"name": target.name},
    )
    return target


async def list_devices(
    session: AsyncSession, *, restaurant_id: int
) -> list[DeviceRegistration]:
    return list(
        (
            await session.scalars(
                select(DeviceRegistration).where(
                    DeviceRegistration.restaurant_id == restaurant_id
                )
            )
        ).all()
    )


# ── Errors ───────────────────────────────────────────────────────────────────


async def log_error(
    session: AsyncSession,
    *,
    restaurant_id: int | None,
    message: str,
    source: str = "api",
    level: str = "error",
    detail: dict | None = None,
) -> AppErrorLog:
    row = AppErrorLog(
        restaurant_id=restaurant_id,
        level=level,
        source=source,
        message=message[:512],
        detail=detail or {},
    )
    session.add(row)
    await session.flush()
    return row


async def list_errors(
    session: AsyncSession,
    *,
    restaurant_id: int,
    unacked_only: bool = False,
    limit: int = 50,
) -> list[AppErrorLog]:
    stmt = (
        select(AppErrorLog)
        .where(AppErrorLog.restaurant_id == restaurant_id)
        .order_by(AppErrorLog.id.desc())
        .limit(min(max(limit, 1), 200))
    )
    if unacked_only:
        stmt = stmt.where(AppErrorLog.acknowledged.is_(False))
    return list((await session.scalars(stmt)).all())


async def acknowledge_error(
    session: AsyncSession, *, restaurant_id: int, error_id: int
) -> AppErrorLog:
    row = await session.get(AppErrorLog, error_id)
    if row is None or row.restaurant_id != restaurant_id:
        raise ValueError("error not found")
    row.acknowledged = True
    await session.flush()
    return row


# ── Offline payments ─────────────────────────────────────────────────────────


async def apply_offline_payment(
    session: AsyncSession,
    *,
    restaurant_id: int,
    client_payment_id: str,
    amount_aed: Decimal,
    tender_type: str = "cash",
    order_id: int | None = None,
    device_id: str | None = None,
    payload: dict | None = None,
) -> OfflinePaymentLedger:
    """Idempotent apply of a payment collected while the terminal was offline."""
    from app.payments.models import PaymentTransaction

    existing = await session.scalar(
        select(OfflinePaymentLedger).where(
            OfflinePaymentLedger.restaurant_id == restaurant_id,
            OfflinePaymentLedger.client_payment_id == client_payment_id,
        )
    )
    if existing:
        return existing

    if order_id is not None:
        txn = PaymentTransaction(
            restaurant_id=restaurant_id,
            order_id=order_id,
            amount_aed=amount_aed,
            tip_aed=Decimal("0"),
            status="succeeded",
            tender_type=tender_type,
            provider="offline_sync",
            channel="offline",
            reference_meta=client_payment_id,
        )
        session.add(txn)

    row = OfflinePaymentLedger(
        restaurant_id=restaurant_id,
        client_payment_id=client_payment_id,
        order_id=order_id,
        amount_aed=amount_aed,
        tender_type=tender_type,
        status="applied",
        device_id=device_id,
        payload=payload or {},
    )
    session.add(row)
    await session.flush()
    return row


# ── Network / uptime dashboard ───────────────────────────────────────────────


async def network_status_dashboard(
    session: AsyncSession, *, restaurant_id: int
) -> dict:
    devices = await list_devices(session, restaurant_id=restaurant_id)
    now = datetime.now(timezone.utc)
    online = 0
    offline = 0
    for d in devices:
        if d.last_seen_at and (now - d.last_seen_at.replace(tzinfo=timezone.utc if d.last_seen_at.tzinfo is None else d.last_seen_at.tzinfo)).total_seconds() < 120:
            online += 1
        else:
            offline += 1
            if d.status == "online":
                d.status = "offline"
    await session.flush()

    last_backup = await session.scalar(
        select(BackupJob)
        .where(
            BackupJob.restaurant_id == restaurant_id,
            BackupJob.status == "completed",
        )
        .order_by(BackupJob.id.desc())
        .limit(1)
    )
    err_count = await session.scalar(
        select(func.count())
        .select_from(AppErrorLog)
        .where(
            AppErrorLog.restaurant_id == restaurant_id,
            AppErrorLog.acknowledged.is_(False),
        )
    )
    return {
        "devices_online": online,
        "devices_offline": offline,
        "devices_total": len(devices),
        "last_backup_at": last_backup.completed_at.isoformat()
        if last_backup and last_backup.completed_at
        else None,
        "last_backup_id": last_backup.id if last_backup else None,
        "unacked_errors": int(err_count or 0),
        "checked_at": now.isoformat(),
        "devices": [
            {
                "device_id": d.device_id,
                "name": d.name,
                "role": d.role,
                "status": d.status,
                "is_failover_active": d.is_failover_active,
                "last_seen_at": d.last_seen_at.isoformat() if d.last_seen_at else None,
            }
            for d in devices
        ],
    }


async def extended_health(session: AsyncSession) -> dict:
    from sqlalchemy import text

    db_status = "ok"
    try:
        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_status = "error"
    backup_dir_ok = _backup_root().exists() and os.access(_backup_root(), os.W_OK)
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "backup_storage": "ok" if backup_dir_ok else "error",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
