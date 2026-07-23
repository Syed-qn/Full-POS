from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.audit.context import get_actor_staff_id
from app.db import get_session
from app.staff.deps import require_role
from app.kds import service as kds_service
from app.kds.models import CategoryStationDefault, KitchenStation, PrintJob
from app.kds.printer_status import get_printer_status, record_printer_heartbeat
from app.kds.schemas import (
    BumpIn,
    CategoryDefaultIn,
    CategoryDefaultOut,
    KitchenPerformanceOut,
    MissingItemIn,
    MissingItemOut,
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


async def _get_owned_station(
    session: AsyncSession, *, station_id: int, restaurant_id: int
) -> KitchenStation:
    station = await session.get(KitchenStation, station_id)
    if station is None or station.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="station not found")
    return station


async def _get_owned_item(
    session: AsyncSession, *, item_id: int, restaurant_id: int
) -> OrderItem:
    item = await session.get(OrderItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    order = await session.get(Order, item.order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="item not found")
    return item


async def _table_labels_for(session: AsyncSession, order: Order | None) -> dict[int, str]:
    """{table_id: label} for a single order — keeps dine-in tickets showing their
    table after a mutation (bump / start-prep / ready) the same as on the board."""
    if order is None or getattr(order, "table_id", None) is None:
        return {}
    from app.tables.models import DiningTable

    table = await session.get(DiningTable, order.table_id)
    return {table.id: table.label} if table is not None else {}


async def _dish_category_for(session: AsyncSession, item: OrderItem) -> dict[int, str]:
    """{dish_id: category} for one item — keeps the board chip showing the real
    menu category after a mutation, same as on the list endpoint."""
    if item.dish_id is None:
        return {}
    from app.menu.models import Dish

    dish = await session.get(Dish, item.dish_id)
    return {dish.id: dish.category} if dish is not None and dish.category else {}


@router.post("/stations", response_model=StationOut, status_code=status.HTTP_201_CREATED)
async def create_station(
    body: StationIn,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    try:
        stype = kds_service.validate_station_type(body.station_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    data = body.model_dump()
    data["station_type"] = stype
    if data.get("fallback_station_id") is not None:
        await _get_owned_station(
            session, station_id=data["fallback_station_id"], restaurant_id=restaurant.id
        )
    station = KitchenStation(restaurant_id=restaurant.id, **data)
    session.add(station)
    await session.commit()
    await session.refresh(station)
    return station


@router.get("/stations", response_model=list[StationOut])
async def list_stations(
    kitchen_code: str | None = Query(default=None),
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(KitchenStation).where(KitchenStation.restaurant_id == restaurant.id)
    if kitchen_code:
        stmt = stmt.where(KitchenStation.kitchen_code == kitchen_code)
    rows = await session.scalars(stmt.order_by(KitchenStation.kitchen_code, KitchenStation.name))
    return list(rows)


@router.post("/stations/seed-defaults", response_model=list[StationOut])
async def seed_default_stations(
    kitchen_code: str = Query(default="main"),
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    """Create grill/fry/beverage/dessert/pizza/cloud/main presets for a kitchen."""
    stations = await kds_service.ensure_default_stations(
        session, restaurant_id=restaurant.id, kitchen_code=kitchen_code
    )
    await session.commit()
    return stations


@router.post(
    "/category-defaults",
    response_model=CategoryDefaultOut,
    status_code=status.HTTP_201_CREATED,
)
async def upsert_category_default(
    body: CategoryDefaultIn,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    try:
        row = await kds_service.set_category_station_default(
            session,
            restaurant_id=restaurant.id,
            category=body.category,
            station_id=body.station_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(row)
    return row


@router.get("/category-defaults", response_model=list[CategoryDefaultOut])
async def list_category_defaults(
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(CategoryStationDefault).where(
            CategoryStationDefault.restaurant_id == restaurant.id
        )
    )
    return list(rows)


@router.get("/stations/{station_id}/tickets", response_model=list[TicketItemOut])
async def station_tickets(
    station_id: int,
    include_ready: bool = Query(default=False),
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    """Active tickets for a station — oldest first, rush/priority floated up."""
    await _get_owned_station(session, station_id=station_id, restaurant_id=restaurant.id)
    return await kds_service.list_station_tickets(
        session,
        restaurant_id=restaurant.id,
        station_id=station_id,
        include_ready=include_ready,
    )


@router.patch("/items/{item_id}/bump", response_model=TicketItemOut)
async def bump_item(
    item_id: int,
    body: BumpIn | None = None,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    before = {"kitchen_status": item.kitchen_status}
    item.kitchen_status = "ready"
    item.bumped_at = datetime.now(timezone.utc)
    # Who called it away: an explicit staff_id wins, otherwise whoever's KDS
    # session made the call. Without this the bump is anonymous and the service
    # record can only say "ready", never by whom.
    bumped_by = (body.staff_id if body else None) or get_actor_staff_id()
    if bumped_by is not None:
        item.bumped_by_staff_id = bumped_by
    await record_audit(
        session,
        actor="kitchen",
        entity="order_item",
        entity_id=str(item.id),
        action="bump",
        restaurant_id=restaurant.id,
        before=before,
        after={"kitchen_status": item.kitchen_status, "staff_id": bumped_by},
    )
    await session.commit()
    order = await session.get(Order, item.order_id)
    return kds_service.enrich_ticket(
        item,
        order,
        table_labels=await _table_labels_for(session, order),
        dish_categories=await _dish_category_for(session, item),
    )


@router.patch("/items/{item_id}/start-prep", response_model=TicketItemOut)
async def start_prep(
    item_id: int,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    item.kitchen_status = "preparing"
    await session.commit()
    order = await session.get(Order, item.order_id)
    return kds_service.enrich_ticket(
        item,
        order,
        table_labels=await _table_labels_for(session, order),
        dish_categories=await _dish_category_for(session, item),
    )


@router.patch("/items/{item_id}/recall", response_model=TicketItemOut)
async def recall_item(
    item_id: int,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    before = {"kitchen_status": item.kitchen_status}
    item.kitchen_status = "received"
    item.bumped_at = None
    item.bumped_by_staff_id = None
    await record_audit(
        session,
        actor="kitchen",
        entity="order_item",
        entity_id=str(item.id),
        action="recall",
        restaurant_id=restaurant.id,
        before=before,
        after={"kitchen_status": item.kitchen_status},
    )
    await session.commit()
    order = await session.get(Order, item.order_id)
    return kds_service.enrich_ticket(
        item,
        order,
        table_labels=await _table_labels_for(session, order),
        dish_categories=await _dish_category_for(session, item),
    )


@router.post("/items/{item_id}/packaging-check", response_model=PackagingCheckOut)
async def packaging_check(
    item_id: int,
    restaurant=Depends(require_role("manager", "kitchen")),
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
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    updated = await kds_service.mark_quality_checked(
        session, restaurant_id=restaurant.id, order_item_id=item.id
    )
    await session.commit()
    await session.refresh(updated)
    return updated


@router.post("/items/{item_id}/missing-item", response_model=MissingItemOut)
async def missing_item_confirm(
    item_id: int,
    body: MissingItemIn | None = None,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    item = await _get_owned_item(session, item_id=item_id, restaurant_id=restaurant.id)
    updated = await kds_service.mark_missing_item(
        session,
        restaurant_id=restaurant.id,
        order_item_id=item.id,
        note=body.note if body else None,
    )
    await record_audit(
        session,
        actor="kitchen",
        entity="order_item",
        entity_id=str(item.id),
        action="missing_item_confirmed",
        restaurant_id=restaurant.id,
        after={"note": body.note if body else None},
    )
    await session.commit()
    await session.refresh(updated)
    return updated


@router.get("/ready-for-pickup", response_model=list[ReadyForPickupOrderOut])
async def ready_for_pickup(
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    by_order = await kds_service.list_ready_for_pickup(session, restaurant_id=restaurant.id)
    result = []
    for order_id, items in by_order.items():
        order = await session.get(Order, order_id)
        result.append(
            {
                "order_id": order_id,
                "order_number": order.order_number if order else "",
                "items": items,
            }
        )
    return result


@router.get("/performance", response_model=KitchenPerformanceOut)
async def kitchen_performance(
    start_date: date = Query(...),
    end_date: date = Query(...),
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    return await kds_service.kitchen_performance_report(
        session,
        restaurant_id=restaurant.id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/print-jobs/pending", response_model=list[PrintJobOut])
async def pending_print_jobs(
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(PrintJob).where(
            PrintJob.restaurant_id == restaurant.id,
            PrintJob.status == "pending",
        )
    )
    return list(rows)


@router.patch("/print-jobs/{job_id}/status", response_model=PrintJobOut)
async def update_print_job_status(
    job_id: int,
    new_status: str,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    job = await session.get(PrintJob, job_id)
    if job is None or job.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="print job not found")
    job.status = new_status
    if new_status == "failed":
        job.attempts += 1
        # On failure, try re-routing to fallback if not already via_fallback.
        if not job.via_fallback:
            station = await session.get(KitchenStation, job.station_id)
            if station and station.fallback_station_id:
                job.original_station_id = job.station_id
                job.station_id = station.fallback_station_id
                job.via_fallback = True
                job.status = "pending"
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
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    await _get_owned_station(session, station_id=station_id, restaurant_id=restaurant.id)
    await record_printer_heartbeat(
        session,
        restaurant_id=restaurant.id,
        station_id=station_id,
        healthy=body.healthy,
    )
    await session.commit()
    statuses = await get_printer_status(session, restaurant_id=restaurant.id)
    return next(s for s in statuses if s["station_id"] == station_id)


@router.get("/printer-status", response_model=list[PrinterStatusOut])
async def printer_status(
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    return await get_printer_status(session, restaurant_id=restaurant.id)
