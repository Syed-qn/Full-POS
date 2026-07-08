from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.kds import service as kds_service
from app.kds.models import KitchenStation, PrintJob
from app.kds.printer_status import get_printer_status, record_printer_heartbeat
from app.kds.schemas import (
    PackagingCheckOut,
    PrinterHeartbeatIn,
    PrinterStatusOut,
    PrintJobOut,
    QualityCheckOut,
    ReadyForPickupOrderOut,
    StationIn,
    StationOut,
    TicketItemOut,
)
from app.ordering.models import Order, OrderItem

router = APIRouter(prefix="/api/v1/kds", tags=["kds"])


@router.post("/stations", response_model=StationOut, status_code=status.HTTP_201_CREATED)
async def create_station(
    body: StationIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    station = KitchenStation(restaurant_id=restaurant.id, **body.model_dump())
    session.add(station)
    await session.commit()
    await session.refresh(station)
    return station


@router.get("/stations", response_model=list[StationOut])
async def list_stations(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(KitchenStation).where(KitchenStation.restaurant_id == restaurant.id)
    )
    return list(rows)


async def _get_owned_station(session: AsyncSession, *, station_id: int, restaurant_id: int) -> KitchenStation:
    station = await session.get(KitchenStation, station_id)
    if station is None or station.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="station not found")
    return station


async def _get_owned_item(session: AsyncSession, *, item_id: int, restaurant_id: int) -> OrderItem:
    item = await session.get(OrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    order = await session.get(Order, item.order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="item not found")
    return item


@router.get("/stations/{station_id}/tickets", response_model=list[TicketItemOut])
async def station_tickets(
    station_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_station(session, station_id=station_id, restaurant_id=restaurant.id)
    rows = await session.scalars(
        select(OrderItem).where(
            OrderItem.station_id_snapshot == station_id,
            OrderItem.kitchen_status == "received",
        )
    )
    return list(rows)


@router.patch("/items/{item_id}/bump", response_model=TicketItemOut)
async def bump_item(
    item_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    before = {"kitchen_status": item.kitchen_status}
    item.kitchen_status = "ready"
    item.bumped_at = datetime.now(timezone.utc)
    await record_audit(
        session, actor="kitchen", entity="order_item", entity_id=str(item.id),
        action="bump", restaurant_id=restaurant.id, before=before,
        after={"kitchen_status": item.kitchen_status},
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.patch("/items/{item_id}/recall", response_model=TicketItemOut)
async def recall_item(
    item_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    before = {"kitchen_status": item.kitchen_status}
    item.kitchen_status = "received"
    item.bumped_at = None
    await record_audit(
        session, actor="kitchen", entity="order_item", entity_id=str(item.id),
        action="recall", restaurant_id=restaurant.id, before=before,
        after={"kitchen_status": item.kitchen_status},
    )
    await session.commit()
    await session.refresh(item)
    return item


@router.post("/items/{item_id}/packaging-check", response_model=PackagingCheckOut)
async def packaging_check(
    item_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    updated = await kds_service.mark_packaging_checked(
        session, restaurant_id=restaurant.id, order_item_id=item.id
    )
    await session.commit()
    await session.refresh(updated)
    return updated


@router.post("/items/{item_id}/quality-check", response_model=QualityCheckOut)
async def quality_check(
    item_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    updated = await kds_service.mark_quality_checked(
        session, restaurant_id=restaurant.id, order_item_id=item.id
    )
    await session.commit()
    await session.refresh(updated)
    return updated


@router.get("/ready-for-pickup", response_model=list[ReadyForPickupOrderOut])
async def ready_for_pickup(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    by_order = await kds_service.list_ready_for_pickup(session, restaurant_id=restaurant.id)
    result = []
    for order_id, items in by_order.items():
        order = await session.get(Order, order_id)
        result.append({
            "order_id": order_id,
            "order_number": order.order_number if order else "",
            "items": items,
        })
    return result


@router.get("/print-jobs/pending", response_model=list[PrintJobOut])
async def pending_print_jobs(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(PrintJob).where(
            PrintJob.restaurant_id == restaurant.id, PrintJob.status == "pending",
        )
    )
    return list(rows)


@router.patch("/print-jobs/{job_id}/status", response_model=PrintJobOut)
async def update_print_job_status(
    job_id: int,
    new_status: str,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(PrintJob, job_id)
    if job is None or job.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="print job not found")
    job.status = new_status
    if new_status == "failed":
        job.attempts += 1
    await session.commit()
    await session.refresh(job)
    return job


@router.post(
    "/stations/{station_id}/printer-heartbeat",
    response_model=PrinterStatusOut,
    status_code=status.HTTP_201_CREATED,
)
async def printer_heartbeat(
    station_id: int,
    body: PrinterHeartbeatIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Called periodically by a printer/kiosk client to report itself alive.
    Knowing a printer died is the prerequisite for falling back to another one."""
    await _get_owned_station(session, station_id=station_id, restaurant_id=restaurant.id)
    await record_printer_heartbeat(
        session, restaurant_id=restaurant.id, station_id=station_id, healthy=body.healthy,
    )
    await session.commit()
    statuses = await get_printer_status(session, restaurant_id=restaurant.id)
    return next(s for s in statuses if s["station_id"] == station_id)


@router.get("/printer-status", response_model=list[PrinterStatusOut])
async def printer_status(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await get_printer_status(session, restaurant_id=restaurant.id)
