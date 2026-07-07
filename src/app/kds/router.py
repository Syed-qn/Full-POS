from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.kds.models import KitchenStation, PrintJob
from app.kds.schemas import PrintJobOut, StationIn, StationOut, TicketItemOut
from app.ordering.models import OrderItem

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


@router.get("/stations/{station_id}/tickets", response_model=list[TicketItemOut])
async def station_tickets(
    station_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
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
    item = await session.get(OrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
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
    item = await session.get(OrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
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
    if job is None:
        raise HTTPException(status_code=404, detail="print job not found")
    job.status = new_status
    if new_status == "failed":
        job.attempts += 1
    await session.commit()
    await session.refresh(job)
    return job
