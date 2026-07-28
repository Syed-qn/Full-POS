from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.audit.context import get_actor_staff_id
from app.db import get_session
from app.staff.deps import current_staff_id, require_role
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
    ReadyAlertOut,
    ReadyForPickupOrderOut,
    StationIn,
    StationPatch,
    StationOut,
    TicketItemOut,
)
from app.ordering.models import Order, OrderItem

router = APIRouter(prefix="/api/v1/kds", tags=["kds"])

# Two role sets on purpose.
#
# WORKING the board — reading tickets, bumping, recalling, the checks, printer
# state — is open to the whole floor: manager, kitchen, cashier and waiter. In a
# small restaurant the same person plates and rings up, and the frontend already
# offered /kds to all of them, so restricting it here only produced a screen
# that loaded and then 403'd on every call.
#
# CONFIGURING it — creating, renaming or deleting a kitchen, and the category
# routing that decides which dishes print where — stays with manager and
# kitchen. That is setup done once, not service work, and a mis-tap there
# silently sends every dish in a category to the wrong pass.
#
# Neither set widens tenancy: every handler still resolves the row against the
# restaurant in the caller's token (see tests/kds/test_kitchen_isolation.py).


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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(CategoryStationDefault).where(
            CategoryStationDefault.restaurant_id == restaurant.id
        )
    )
    return list(rows)


@router.patch("/stations/{station_id}", response_model=StationOut)
async def update_station(
    station_id: int,
    body: StationPatch,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    """Rename a kitchen or toggle it active. The Main kitchen is the routing
    fallback (any dish not wired lands there), so it can be deactivated but not
    renamed away from "Main" — that would orphan the fallback."""
    station = await _get_owned_station(
        session, station_id=station_id, restaurant_id=restaurant.id
    )
    changes = body.model_dump(exclude_unset=True)
    if station.name == "Main" and "name" in changes and changes["name"] != "Main":
        raise HTTPException(status_code=409, detail="The Main kitchen cannot be renamed.")
    if "name" in changes:
        new_name = (changes["name"] or "").strip()
        if not new_name:
            raise HTTPException(status_code=422, detail="Kitchen name cannot be empty.")
        dup = await session.scalar(
            select(KitchenStation).where(
                KitchenStation.restaurant_id == restaurant.id,
                KitchenStation.kitchen_code == station.kitchen_code,
                KitchenStation.name == new_name,
                KitchenStation.id != station.id,
            )
        )
        if dup is not None:
            raise HTTPException(status_code=409, detail="A kitchen with that name exists.")
        changes["name"] = new_name
    before = {k: getattr(station, k) for k in changes}
    for key, value in changes.items():
        setattr(station, key, value)
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id,
        entity="kitchen_station", entity_id=str(station.id), action="station_edited",
        before=before, after=changes,
    )
    await session.commit()
    await session.refresh(station)
    return station


@router.delete("/stations/{station_id}", status_code=204)
async def delete_station(
    station_id: int,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    """Delete a kitchen and re-home everything pointing at it to Main, so nothing
    is ever orphaned: category wirings drop (fall back to Main), dish overrides
    clear, and any in-flight tickets move to Main's board. The Main kitchen
    itself cannot be deleted — it is the fallback."""
    from app.menu.models import Dish
    from app.ordering.models import OrderItem

    station = await _get_owned_station(
        session, station_id=station_id, restaurant_id=restaurant.id
    )
    if station.name == "Main":
        raise HTTPException(status_code=409, detail="The Main kitchen cannot be deleted.")

    main = await kds_service.get_or_create_main_station(
        session, restaurant_id=restaurant.id, kitchen_code=station.kitchen_code
    )

    # Category wirings → drop (unwired categories fall back to Main).
    defaults = (
        await session.scalars(
            select(CategoryStationDefault).where(
                CategoryStationDefault.restaurant_id == restaurant.id,
                CategoryStationDefault.station_id == station.id,
            )
        )
    ).all()
    for d in defaults:
        await session.delete(d)

    # Dish overrides → clear (fall back to category default / Main).
    dishes = (
        await session.scalars(
            select(Dish).where(
                Dish.restaurant_id == restaurant.id, Dish.station_id == station.id
            )
        )
    ).all()
    for dish in dishes:
        dish.station_id = None

    # In-flight tickets snapshotted to this station → move to Main's board.
    items = (
        await session.scalars(
            select(OrderItem).where(OrderItem.station_id_snapshot == station.id)
        )
    ).all()
    for it in items:
        it.station_id_snapshot = main.id

    # Everything else that FK-references this station must be cleared/re-homed
    # first, or the DELETE hits a foreign-key violation (the real reason "Remove"
    # failed in production once a kitchen had ever fired a ticket).
    from app.kds.printer_status import PrinterStatus

    # Print jobs (station_id is NOT NULL) → re-home to Main; drop the now-stale
    # "original station" pointer where it named this station.
    print_jobs = (
        await session.scalars(
            select(PrintJob).where(PrintJob.station_id == station.id)
        )
    ).all()
    for job in print_jobs:
        job.station_id = main.id
    orig_jobs = (
        await session.scalars(
            select(PrintJob).where(PrintJob.original_station_id == station.id)
        )
    ).all()
    for job in orig_jobs:
        job.original_station_id = None

    # Printer heartbeat rows are per-station and meaningless once it is gone.
    statuses = (
        await session.scalars(
            select(PrinterStatus).where(PrinterStatus.station_id == station.id)
        )
    ).all()
    for st in statuses:
        await session.delete(st)

    # Any other station using this one as its printer fallback → clear it.
    fallbacks = (
        await session.scalars(
            select(KitchenStation).where(
                KitchenStation.restaurant_id == restaurant.id,
                KitchenStation.fallback_station_id == station.id,
            )
        )
    ).all()
    for fb in fallbacks:
        fb.fallback_station_id = None

    await session.flush()

    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id,
        entity="kitchen_station", entity_id=str(station.id), action="station_deleted",
        before={"name": station.name, "kitchen_code": station.kitchen_code},
        after={"reassigned_to_main": main.id, "categories_dropped": len(defaults),
               "dishes_cleared": len(dishes), "tickets_moved": len(items)},
    )
    await session.delete(station)
    await session.commit()
    return None


@router.delete("/category-defaults/{category}", status_code=204)
async def delete_category_default(
    category: str,
    restaurant=Depends(require_role("manager", "kitchen")),
    session: AsyncSession = Depends(get_session),
):
    """Unwire a category so its dishes fall back to Main (or their dish override)."""
    row = await session.scalar(
        select(CategoryStationDefault).where(
            CategoryStationDefault.restaurant_id == restaurant.id,
            CategoryStationDefault.category == category,
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Category is not wired.")
    await session.delete(row)
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id,
        entity="category_station_default", entity_id=category, action="category_unwired",
        before={"category": category, "station_id": row.station_id}, after={},
    )
    await session.commit()
    return None


@router.get("/stations/{station_id}/tickets", response_model=list[TicketItemOut])
async def station_tickets(
    station_id: int,
    include_ready: bool = Query(default=False),
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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

    # Order-level READY: when every non-cancelled line on a PREPARING order has
    # been bumped, the whole order is ready. Advance it so the cashier's WhatsApp
    # queue reflects "Ready" and delivery orders enter auto-dispatch. Bumping a
    # single line never moved the order before, so an order could sit in PREPARING
    # forever with all its food plated.
    if order is not None and str(order.status) == "preparing":
        remaining = await session.scalar(
            select(OrderItem)
            .where(
                OrderItem.order_id == order.id,
                OrderItem.cancelled.is_(False),
                OrderItem.kitchen_status != "ready",
            )
            .limit(1)
        )
        if remaining is None:
            from app.ordering.service import advance_kitchen_status

            try:
                order = await advance_kitchen_status(session, order=order, actor="kitchen")
            except ValueError:
                # A concurrent transition already moved it — the board is still correct.
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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


@router.get("/ready-alerts", response_model=list[ReadyAlertOut])
async def ready_alerts(
    since: datetime | None = Query(default=None),
    restaurant=Depends(require_role("manager", "cashier", "waiter", "kitchen")),
    staff_id: int | None = Depends(current_staff_id),
    session: AsyncSession = Depends(get_session),
):
    """"Your order is ready" pings for the CURRENT staff member (the order's
    creator) — powers the waiter/cashier top-bar bell.

    Whole-order readiness: an order qualifies when every non-cancelled line has
    been bumped (``kitchen_status == "ready"``). ``since`` is the client's
    watermark (ISO 8601); only orders whose latest bump is newer are returned,
    so a poll never re-alerts the same order and the first load (``since`` = now)
    returns nothing. Scoped to ``Order.staff_id == me``, which is why a
    cashier-created order only rings the cashier and a waiter's table only rings
    that waiter — no cross-talk. Manager/owner tokens carry no staff id and get
    an empty list (they use the manager alert center)."""
    from collections import defaultdict
    from datetime import timedelta

    if staff_id is None:
        return []

    def _naive_utc(dt: datetime) -> datetime:
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    since_ts = _naive_utc(since) if since is not None else now
    # Only look at recent orders — a shift's worth — so the scan stays cheap.
    cutoff = now - timedelta(hours=12)

    orders = (
        await session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant.id,
                Order.staff_id == staff_id,
                Order.status.notin_(["delivered", "cancelled"]),
                Order.created_at >= cutoff,
            )
        )
    ).all()
    if not orders:
        return []
    order_by_id = {o.id: o for o in orders}

    items = (
        await session.scalars(
            select(OrderItem).where(OrderItem.order_id.in_(list(order_by_id.keys())))
        )
    ).all()
    items_by_order: dict[int, list[OrderItem]] = defaultdict(list)
    for it in items:
        items_by_order[it.order_id].append(it)

    # Resolve dine-in table labels in one pass.
    from app.tables.models import DiningTable

    table_ids = {o.table_id for o in orders if getattr(o, "table_id", None) is not None}
    labels: dict[int, str] = {}
    if table_ids:
        for t in (
            await session.scalars(
                select(DiningTable).where(DiningTable.id.in_(list(table_ids)))
            )
        ).all():
            labels[t.id] = t.label

    result: list[ReadyAlertOut] = []
    for oid, its in items_by_order.items():
        active = [i for i in its if not i.cancelled]
        if not active:
            continue
        if any(i.kitchen_status != "ready" for i in active):
            continue  # still cooking — not the whole order yet
        stamps = [_naive_utc(i.bumped_at) for i in active if i.bumped_at is not None]
        if not stamps:
            continue
        ready_at = max(stamps)
        if ready_at <= since_ts:
            continue  # already alerted before the client's watermark
        o = order_by_id[oid]
        result.append(
            ReadyAlertOut(
                order_id=o.id,
                order_number=o.order_number,
                daily_token=getattr(o, "daily_token", None),
                table_label=labels.get(getattr(o, "table_id", None)),
                order_type=getattr(o, "order_type", None),
                ready_at=ready_at.isoformat(),
            )
        )

    result.sort(key=lambda r: r.ready_at, reverse=True)
    return result[:20]


@router.get("/performance", response_model=KitchenPerformanceOut)
async def kitchen_performance(
    start_date: date = Query(...),
    end_date: date = Query(...),
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
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
    restaurant=Depends(require_role("manager", "kitchen", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
):
    return await get_printer_status(session, restaurant_id=restaurant.id)
