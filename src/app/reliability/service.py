"""Backup snapshots, device registry, offline payment apply, DR drills."""

from __future__ import annotations

import base64
import hashlib
import importlib
import json
import pkgutil
import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import Table, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.config import get_settings
from app.db import Base
from app.reliability import storage
from app.reliability.models import (
    AppErrorLog,
    BackupJob,
    DeviceRegistration,
    DrDrillLog,
    OfflinePaymentLedger,
)

SNAPSHOT_FORMAT = 2

# Tables that describe THIS deployment's plumbing rather than the restaurant's
# business data. Restoring them would resurrect dead terminals, replay queued
# outbound messages to customers, and overwrite the very backup ledger being
# restored from — so they are captured for forensics but never written back.
_NEVER_RESTORE = frozenset(
    {
        "backup_jobs",
        "dr_drill_logs",
        "app_error_logs",
        "device_registrations",
        "outbox_messages",
        "idempotency_keys",
        "webhook_events",
    }
)

_models_imported = False


def _ensure_models_imported() -> None:
    """Populate Base.metadata with every tenant table.

    The snapshot is driven by metadata, not by a hand-written column list — that
    list is exactly what made the old snapshot silently partial (no tables, no
    payments, no shifts). Walking the packages means a module added next month is
    backed up without anyone remembering to edit this file.
    """
    global _models_imported
    if _models_imported:
        return
    import app  # noqa: PLC0415

    for mod in pkgutil.iter_modules(app.__path__):
        if not mod.ispkg:
            continue
        for leaf in ("models", "modifiers", "combos", "pricing", "scheduling", "printer_status"):
            try:
                importlib.import_module(f"app.{mod.name}.{leaf}")
            except ModuleNotFoundError:
                continue
    _models_imported = True


def _tenant_tables() -> list[Table]:
    """Every table carrying restaurant_id, in FK-safe (parent-first) order."""
    _ensure_models_imported()
    return [t for t in Base.metadata.sorted_tables if "restaurant_id" in t.c]


def _jsonable(value):
    """Lossless-enough JSON encoding: what goes out must come back identical."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": base64.b64encode(bytes(value)).decode("ascii")}
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _decode(col, value):
    """Turn a JSON scalar back into what the driver expects for this column.

    JSON has no datetime, no Decimal and no UUID, so the snapshot stores them as
    strings. asyncpg is strict — handing it '2026-07-31T10:28:32' for a TIMESTAMP
    column raises DataError — so the column's own Python type decides how each
    value is read back.
    """
    if isinstance(value, dict) and set(value) == {"__bytes__"}:
        return base64.b64decode(value["__bytes__"])
    if value is None or not isinstance(value, str):
        return value
    try:
        target = col.type.python_type
    except NotImplementedError:
        return value
    if target is datetime:
        return datetime.fromisoformat(value)
    if target is date:
        return date.fromisoformat(value)
    if target is time:
        return time.fromisoformat(value)
    if target is Decimal:
        return Decimal(value)
    if target is uuid.UUID:
        return uuid.UUID(value)
    return value


async def create_backup_snapshot(
    session: AsyncSession,
    *,
    restaurant_id: int,
    kind: str = "manual",
) -> BackupJob:
    """Serialize EVERY tenant-owned table to a JSON snapshot in durable storage.

    Previously this dumped six hand-picked tables with a handful of columns each
    and capped orders at 5000 — a snapshot you could not rebuild a business from,
    presented in the UI as a backup. It now walks the mapped metadata, so a table
    is included by virtue of carrying ``restaurant_id``, and every column comes
    with it.
    """
    job = BackupJob(
        restaurant_id=restaurant_id,
        kind=kind,
        status="running",
    )
    session.add(job)
    await session.flush()

    try:
        cap = get_settings().backup_max_rows_per_table
        tables = _tenant_tables()
        dumped: dict[str, list[dict]] = {}
        counts: dict[str, int] = {}
        truncated: list[str] = []

        for table in tables:
            # Ordered by primary key so a self-referencing row (a table joined
            # onto another table) is written after the row it points at, which
            # is what lets a restore insert them back in file order.
            stmt = select(table).where(table.c.restaurant_id == restaurant_id)
            pks = list(table.primary_key.columns)
            if pks:
                stmt = stmt.order_by(*pks)
            rows = (await session.execute(stmt.limit(cap + 1))).mappings().all()
            if len(rows) > cap:
                rows = rows[:cap]
                truncated.append(table.name)
            dumped[table.name] = [dict(r) for r in rows]
            counts[table.name] = len(rows)

        # The restaurant row itself keys on `id`, not `restaurant_id`, so the
        # metadata sweep above misses it — and without it a restore has no tenant
        # to hang anything off.
        from app.identity.models import Restaurant  # noqa: PLC0415

        rest = (
            await session.execute(
                select(Restaurant.__table__).where(Restaurant.__table__.c.id == restaurant_id)
            )
        ).mappings().all()
        dumped["restaurants"] = [dict(r) for r in rest]
        counts["restaurants"] = len(rest)

        payload = {
            "format": SNAPSHOT_FORMAT,
            "restaurant_id": restaurant_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            # Insert order for a restore. Reverse it to delete.
            "table_order": ["restaurants", *[t.name for t in tables]],
            "tables": dumped,
            "counts": counts,
            "truncated": truncated,
            "row_cap": cap,
        }
        raw = json.dumps(payload, separators=(",", ":"), default=_jsonable).encode("utf-8")
        checksum = hashlib.sha256(raw).hexdigest()
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        filename = f"r{restaurant_id}_{kind}_{ts}_{checksum[:8]}.json"
        uri = await storage.put_backup(filename, raw)

        job.status = "completed"
        job.storage_path = uri
        job.size_bytes = len(raw)
        job.checksum = checksum
        # Only non-empty tables, so the UI summary stays readable next to ~120
        # mapped tables of which a small restaurant fills a dozen.
        job.meta = {
            "backend": storage.active_backend(),
            "truncated": truncated,
            "counts": {k: v for k, v in counts.items() if v},
        }
        job.completed_at = datetime.now(timezone.utc)
        await session.flush()
        await record_audit(
            session,
            restaurant_id=restaurant_id,
            actor="system",
            entity="backup_job",
            entity_id=str(job.id),
            action="backup_completed",
            after={"path": uri, "size": len(raw), "checksum": checksum},
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
    """Create a daily backup if none completed today, in the restaurant's own day."""
    existing = await _todays_backup(session, restaurant_id=restaurant_id)
    if existing:
        return existing
    return await create_backup_snapshot(
        session, restaurant_id=restaurant_id, kind="daily"
    )


def _business_day_start_utc() -> datetime:
    """Midnight tonight in Asia/Dubai, expressed in UTC.

    "Today" used to mean the UTC day. Dubai is UTC+4, so a restaurant closing at
    2am and pressing Ensure daily backup would be told one already exists — the
    previous evening's, which UTC still counts as the same day. The server's day
    has to be the restaurant's day or the answer is wrong exactly when someone is
    standing there at closing time.
    """
    local = datetime.now(ZoneInfo("Asia/Dubai"))
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


async def _todays_backup(
    session: AsyncSession, *, restaurant_id: int
) -> BackupJob | None:
    return await session.scalar(
        select(BackupJob)
        .where(
            BackupJob.restaurant_id == restaurant_id,
            BackupJob.status == "completed",
            BackupJob.completed_at >= _business_day_start_utc(),
        )
        .order_by(BackupJob.id.desc())
        .limit(1)
    )


async def verify_backup(
    session: AsyncSession, *, restaurant_id: int, backup_job_id: int
) -> dict:
    """Answer the only question worth asking: WILL THIS RESTORE?

    A checksum alone proves the bytes are unchanged, which is not the same
    thing. A snapshot can match its checksum perfectly and still be unusable —
    truncated JSON, an older format Restore cannot read, or another tenant's
    data. Finding that out during an actual incident is the worst possible time,
    so every gate the restore path applies is applied here too.
    """
    job = await session.get(BackupJob, backup_job_id)
    if job is None or job.restaurant_id != restaurant_id:
        raise ValueError("backup not found")

    checks: dict[str, bool] = {}
    problems: list[str] = []

    checks["file_present"] = await storage.backup_exists(job.storage_path)
    if not checks["file_present"]:
        raise ValueError("backup file missing")

    raw = await storage.get_backup(job.storage_path)
    checksum = hashlib.sha256(raw).hexdigest()
    checks["checksum_matches"] = checksum == job.checksum
    if not checks["checksum_matches"]:
        problems.append("the file has changed since it was written (corrupted)")

    data: dict = {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
        checks["readable"] = isinstance(parsed, dict)
        data = parsed if isinstance(parsed, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        checks["readable"] = False
    if not checks["readable"]:
        problems.append("the file is damaged and cannot be opened")

    checks["format_supported"] = data.get("format") == SNAPSHOT_FORMAT
    if not checks["format_supported"]:
        problems.append(
            "it was written by an older version and Restore cannot read it — "
            "take a fresh backup"
        )

    checks["right_restaurant"] = data.get("restaurant_id") == restaurant_id
    if not checks["right_restaurant"]:
        problems.append("it belongs to a different restaurant")

    counts = data.get("counts") or {}
    checks["has_data"] = bool(counts.get("restaurants"))
    if not checks["has_data"]:
        problems.append("the restaurant's own record is missing from it")

    ok = all(checks.values())
    drill = DrDrillLog(
        restaurant_id=restaurant_id,
        backup_job_id=job.id,
        kind="verify",
        status="ok" if ok else "failed",
        notes="restorability check",
        detail={
            "expected": job.checksum,
            "actual": checksum,
            "size": len(raw),
            "checks": checks,
        },
    )
    session.add(drill)
    await session.flush()
    return {
        "backup_job_id": job.id,
        "ok": ok,
        "restorable": ok,
        "checks": checks,
        # Plain language, because the person pressing this runs a restaurant.
        "summary": (
            "This backup is complete and can be restored."
            if ok
            else "This backup CANNOT be restored: " + "; ".join(problems) + "."
        ),
        "checksum": checksum,
        "size_bytes": len(raw),
        "drill_id": drill.id,
    }


async def latest_backup_health(
    session: AsyncSession, *, restaurant_id: int
) -> dict:
    """Verify the newest backup so the dashboard can state its health up front.

    Pressing a button and reading a toast that disappears is not an answer to
    "is my data safe?" — the answer has to be on the screen before anyone asks.
    Only the newest is checked: it is the one a restore would use, and reading
    every snapshot on every page load would cost far more than it tells you.
    """
    job = await session.scalar(
        select(BackupJob)
        .where(
            BackupJob.restaurant_id == restaurant_id,
            BackupJob.status == "completed",
        )
        .order_by(BackupJob.id.desc())
        .limit(1)
    )
    today = await _todays_backup(session, restaurant_id=restaurant_id)
    today_info = {
        "backed_up_today": today is not None,
        "today_backup_id": today.id if today else None,
    }
    if job is None:
        return {
            "has_backup": False,
            "ok": False,
            "summary": "No backup has been taken yet.",
            **today_info,
        }
    try:
        result = await verify_backup(
            session, restaurant_id=restaurant_id, backup_job_id=job.id
        )
    except ValueError as exc:
        return {
            "has_backup": True,
            "backup_job_id": job.id,
            "ok": False,
            "taken_at": job.completed_at.isoformat() if job.completed_at else None,
            "size_bytes": job.size_bytes,
            "summary": f"The newest backup cannot be read: {exc}.",
            **today_info,
        }
    return {
        "has_backup": True,
        "backup_job_id": job.id,
        "ok": result["ok"],
        "checks": result["checks"],
        "taken_at": job.completed_at.isoformat() if job.completed_at else None,
        "size_bytes": job.size_bytes,
        "summary": result["summary"],
        **today_info,
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
    if not await storage.backup_exists(job.storage_path):
        raise ValueError("backup file missing")
    data = json.loads((await storage.get_backup(job.storage_path)).decode("utf-8"))
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
        "restore_enabled": get_settings().backup_restore_enabled,
        "message": (
            "Snapshot readable. Use Restore to overwrite this restaurant's data with it."
            if get_settings().backup_restore_enabled
            else "Snapshot readable. Overwrite restore is disabled "
            "(set APP_BACKUP_RESTORE_ENABLED=true to allow it)."
        ),
    }


class RestoreError(RuntimeError):
    """Restore refused — bad confirmation, disabled, or an unusable snapshot."""


async def restore_backup(
    session: AsyncSession,
    *,
    restaurant_id: int,
    backup_job_id: int,
    confirm: str,
    actor: str = "manager",
) -> dict:
    """Overwrite this restaurant's data with a snapshot. Destructive.

    Three gates, because this deletes a live restaurant's history: the feature
    flag must be on, the caller must type the exact phrase, and a ``pre_restore``
    snapshot is taken first so the operation itself is undoable. Everything runs
    in the caller's transaction — a foreign-key failure part-way rolls the whole
    thing back rather than leaving a half-restored tenant.
    """
    settings = get_settings()
    if not settings.backup_restore_enabled:
        raise RestoreError(
            "Overwrite restore is disabled. Set APP_BACKUP_RESTORE_ENABLED=true to allow it."
        )
    expected = f"RESTORE {restaurant_id}"
    if (confirm or "").strip() != expected:
        raise RestoreError(f"confirmation must be exactly '{expected}'")

    job = await session.get(BackupJob, backup_job_id)
    if job is None or job.restaurant_id != restaurant_id:
        raise ValueError("backup not found")
    if not await storage.backup_exists(job.storage_path):
        raise ValueError("backup file missing")

    raw = await storage.get_backup(job.storage_path)
    if hashlib.sha256(raw).hexdigest() != job.checksum:
        raise RestoreError("checksum mismatch — snapshot is corrupt, refusing to restore")
    data = json.loads(raw.decode("utf-8"))
    if data.get("format") != SNAPSHOT_FORMAT:
        raise RestoreError(
            f"snapshot format {data.get('format')} predates full-table backups "
            "and cannot be restored; take a fresh backup first"
        )
    if data.get("restaurant_id") != restaurant_id:
        raise RestoreError("snapshot belongs to a different restaurant")

    # Safety net first: if the restore is wrong, this is what undoes it.
    safety = await create_backup_snapshot(
        session, restaurant_id=restaurant_id, kind="pre_restore"
    )

    by_name = {t.name: t for t in Base.metadata.sorted_tables}
    order = [
        n
        for n in data.get("table_order", [])
        if n in by_name and n not in _NEVER_RESTORE and n != "restaurants"
    ]
    payload = data.get("tables", {})

    deleted: dict[str, int] = {}
    inserted: dict[str, int] = {}

    # Children before parents.
    for name in reversed(order):
        table = by_name[name]
        res = await session.execute(
            delete(table).where(table.c.restaurant_id == restaurant_id)
        )
        if res.rowcount:
            deleted[name] = res.rowcount

    # Parents before children, rows in primary-key order (see the snapshot side).
    for name in order:
        rows = payload.get(name) or []
        if not rows:
            continue
        table = by_name[name]
        cols = table.c
        clean = [
            {k: _decode(cols[k], v) for k, v in row.items() if k in cols}
            for row in rows
        ]
        await session.execute(table.insert(), clean)
        inserted[name] = len(clean)

    # Explicit ids were inserted, so every sequence still points at 1 and the
    # next real order would collide on the primary key. Fast-forward them.
    resequenced = []
    for name in order:
        table = by_name[name]
        for col in table.primary_key.columns:
            try:
                if col.type.python_type is not int:
                    continue
            except NotImplementedError:  # types with no Python equivalent
                continue
            # Identifiers come from mapped metadata, never from a request. The
            # sequence lookup is wrapped in a subquery so setval() is only reached
            # for columns that actually own one.
            await session.execute(
                text(
                    "SELECT setval(x.seq, GREATEST(COALESCE(x.hi, 1), 1), true) FROM ("
                    f'  SELECT pg_get_serial_sequence(:t, :c) AS seq,'
                    f'         (SELECT MAX("{col.name}") FROM "{name}") AS hi'
                    ") x WHERE x.seq IS NOT NULL"
                ),
                {"t": name, "c": col.name},
            )
            resequenced.append(f"{name}.{col.name}")

    drill = DrDrillLog(
        restaurant_id=restaurant_id,
        backup_job_id=job.id,
        kind="restore",
        status="ok",
        notes=f"overwrite restore from backup #{job.id}",
        detail={
            "deleted": deleted,
            "inserted": inserted,
            "pre_restore_backup_id": safety.id,
        },
    )
    session.add(drill)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor=actor,
        entity="backup_job",
        entity_id=str(job.id),
        action="backup_restored",
        after={
            "deleted_rows": sum(deleted.values()),
            "inserted_rows": sum(inserted.values()),
            "pre_restore_backup_id": safety.id,
        },
    )
    return {
        "backup_job_id": job.id,
        "drill_id": drill.id,
        "pre_restore_backup_id": safety.id,
        "deleted": deleted,
        "inserted": inserted,
        "resequenced": len(resequenced),
        "restore_mode": "overwrite",
    }


async def export_full_data_pack(
    session: AsyncSession, *, restaurant_id: int
) -> dict:
    """Export pack for manager download — same snapshot, plus a real download URL.

    This used to hand back ``download_path``: a path on the server's filesystem,
    which a browser cannot open. The manager pressed the button, got a toast, and
    received no file. The URL below is an authenticated endpoint that streams the
    bytes.
    """
    job = await create_backup_snapshot(
        session, restaurant_id=restaurant_id, kind="export"
    )
    return {
        "backup_job_id": job.id,
        "checksum": job.checksum,
        "size_bytes": job.size_bytes,
        "download_url": f"/api/v1/reliability/backups/{job.id}/download",
        "storage_uri": job.storage_path,
        "preview": (job.meta or {}).get("counts"),
    }


async def read_backup_bytes(
    session: AsyncSession, *, restaurant_id: int, backup_job_id: int
) -> tuple[bytes, str]:
    """Fetch a snapshot's bytes plus a filename, for the download endpoint."""
    job = await session.get(BackupJob, backup_job_id)
    if job is None or job.restaurant_id != restaurant_id:
        raise ValueError("backup not found")
    if not await storage.backup_exists(job.storage_path):
        raise ValueError("backup file missing")
    raw = await storage.get_backup(job.storage_path)
    name = (job.storage_path or "").rsplit("/", 1)[-1] or f"backup-{job.id}.json"
    return raw, name


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
    # Round-trip a probe object rather than stat()-ing a directory: on S3 there is
    # no directory to stat, and a local directory that exists but is read-only
    # used to report "ok" right up until the first backup failed.
    target = storage.describe_target()
    try:
        probe = await storage.put_backup(
            ".healthcheck", b'{"probe":true}'
        )
        storage_ok = await storage.backup_exists(probe)
    except Exception:  # noqa: BLE001
        storage_ok = False
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db": db_status,
        "backup_storage": "ok" if storage_ok else "error",
        "backup_target": target,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
