"""HTTP surface for Cat 12 reliability, backups, devices, offline payments."""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.reliability.service import (
    acknowledge_error,
    apply_offline_payment,
    create_backup_snapshot,
    device_heartbeat,
    export_full_data_pack,
    extended_health,
    list_backups,
    list_devices,
    list_errors,
    log_error,
    network_status_dashboard,
    promote_failover_device,
    register_device,
    restore_preview,
    run_daily_backup_if_due,
    verify_backup,
)
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/reliability", tags=["reliability"])


class DeviceIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=64)
    name: str
    device_type: str = "pos"
    role: str = "primary"


class OfflinePaymentIn(BaseModel):
    client_payment_id: str
    amount_aed: Decimal
    tender_type: str = "cash"
    order_id: int | None = None
    device_id: str | None = None
    payload: dict | None = None


class ErrorIn(BaseModel):
    message: str
    source: str = "client"
    level: str = "error"
    detail: dict | None = None


@router.get("/health")
async def reliability_health(session: AsyncSession = Depends(get_session)):
    return await extended_health(session)


@router.get("/network-status")
async def network_status(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await network_status_dashboard(session, restaurant_id=restaurant.id)


@router.post("/backups", status_code=status.HTTP_201_CREATED)
async def create_backup(
    kind: str = Query(default="manual"),
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        job = await create_backup_snapshot(
            session, restaurant_id=restaurant.id, kind=kind
        )
    except Exception as exc:  # noqa: BLE001
        await session.commit()
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": job.id,
        "status": job.status,
        "kind": job.kind,
        "storage_path": job.storage_path,
        "size_bytes": job.size_bytes,
        "checksum": job.checksum,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "meta": job.meta,
    }


@router.post("/backups/daily")
async def daily_backup(
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    job = await run_daily_backup_if_due(session, restaurant_id=restaurant.id)
    await session.commit()
    if job is None:
        return {"status": "skipped"}
    return {
        "id": job.id,
        "status": job.status,
        "kind": job.kind,
        "storage_path": job.storage_path,
        "size_bytes": job.size_bytes,
    }


@router.get("/backups")
async def get_backups(
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_backups(session, restaurant_id=restaurant.id)
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "status": r.status,
            "storage_path": r.storage_path,
            "size_bytes": r.size_bytes,
            "checksum": r.checksum,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
            "meta": r.meta,
            "error": r.error,
        }
        for r in rows
    ]


@router.post("/backups/{backup_id}/verify")
async def verify_backup_endpoint(
    backup_id: int,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await verify_backup(
            session, restaurant_id=restaurant.id, backup_job_id=backup_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return result


@router.post("/backups/{backup_id}/restore-preview")
async def restore_preview_endpoint(
    backup_id: int,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        result = await restore_preview(
            session, restaurant_id=restaurant.id, backup_job_id=backup_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return result


@router.post("/export")
async def export_data(
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    result = await export_full_data_pack(session, restaurant_id=restaurant.id)
    await session.commit()
    return result


@router.post("/devices", status_code=status.HTTP_201_CREATED)
async def post_device(
    body: DeviceIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    row = await register_device(
        session,
        restaurant_id=restaurant.id,
        device_id=body.device_id,
        name=body.name,
        device_type=body.device_type,
        role=body.role,
    )
    await session.commit()
    return {
        "id": row.id,
        "device_id": row.device_id,
        "name": row.name,
        "role": row.role,
        "status": row.status,
    }


@router.get("/devices")
async def get_devices(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_devices(session, restaurant_id=restaurant.id)
    return [
        {
            "id": r.id,
            "device_id": r.device_id,
            "name": r.name,
            "device_type": r.device_type,
            "role": r.role,
            "status": r.status,
            "is_failover_active": r.is_failover_active,
            "last_seen_at": r.last_seen_at.isoformat() if r.last_seen_at else None,
        }
        for r in rows
    ]


@router.post("/devices/{device_id}/heartbeat")
async def post_heartbeat(
    device_id: str,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await device_heartbeat(
            session, restaurant_id=restaurant.id, device_id=device_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"device_id": row.device_id, "status": row.status}


@router.post("/devices/{device_id}/failover")
async def post_failover(
    device_id: str,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await promote_failover_device(
            session, restaurant_id=restaurant.id, device_id=device_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {
        "device_id": row.device_id,
        "role": row.role,
        "is_failover_active": row.is_failover_active,
    }


@router.post("/offline-payments", status_code=status.HTTP_201_CREATED)
async def post_offline_payment(
    body: OfflinePaymentIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    row = await apply_offline_payment(
        session,
        restaurant_id=restaurant.id,
        client_payment_id=body.client_payment_id,
        amount_aed=body.amount_aed,
        tender_type=body.tender_type,
        order_id=body.order_id,
        device_id=body.device_id,
        payload=body.payload,
    )
    await session.commit()
    return {
        "id": row.id,
        "client_payment_id": row.client_payment_id,
        "status": row.status,
        "amount_aed": str(row.amount_aed),
    }


@router.post("/errors", status_code=status.HTTP_201_CREATED)
async def post_error(
    body: ErrorIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    row = await log_error(
        session,
        restaurant_id=restaurant.id,
        message=body.message,
        source=body.source,
        level=body.level,
        detail=body.detail,
    )
    await session.commit()
    return {"id": row.id, "message": row.message}


@router.get("/errors")
async def get_errors(
    unacked_only: bool = False,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    rows = await list_errors(
        session, restaurant_id=restaurant.id, unacked_only=unacked_only
    )
    return [
        {
            "id": r.id,
            "level": r.level,
            "source": r.source,
            "message": r.message,
            "detail": r.detail,
            "acknowledged": r.acknowledged,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/errors/{error_id}/ack")
async def ack_error(
    error_id: int,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await acknowledge_error(
            session, restaurant_id=restaurant.id, error_id=error_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    return {"id": row.id, "acknowledged": row.acknowledged}
