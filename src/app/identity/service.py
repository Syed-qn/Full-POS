# src/app/identity/service.py
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete, func, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.audit import record_audit
from app.identity.auth import hash_password
from app.identity.models import Restaurant, Rider

DUBAI = ZoneInfo("Asia/Dubai")


class DuplicatePhoneError(Exception):
    pass


class RiderHasHistoryError(Exception):
    """Raised when a rider can't be hard-deleted because they hold financial
    records (COD cash / shift reconciliations) that must be preserved — the
    manager should deactivate them instead."""


async def create_restaurant(
    session: AsyncSession,
    *,
    name: str,
    phone: str,
    password: str,
    lat: float,
    lng: float,
) -> Restaurant:
    existing = await session.scalar(select(Restaurant).where(Restaurant.phone == phone))
    if existing:
        raise DuplicatePhoneError("phone already registered")
    restaurant = Restaurant(
        name=name,
        phone=phone,
        password_hash=hash_password(password),
        lat=lat,
        lng=lng,
    )
    session.add(restaurant)
    await session.flush()
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant.id,
        entity="restaurant",
        entity_id=str(restaurant.id),
        action="signup",
        after={"name": name, "phone": phone, "lat": lat, "lng": lng},
    )
    await session.commit()
    return restaurant


async def create_rider(
    session: AsyncSession,
    *,
    restaurant_id: int,
    name: str,
    phone: str,
) -> Rider:
    existing = await session.scalar(
        select(Rider).where(Rider.restaurant_id == restaurant_id, Rider.phone == phone)
    )
    if existing:
        raise DuplicatePhoneError("rider phone already registered")
    rider = Rider(restaurant_id=restaurant_id, name=name, phone=phone)
    session.add(rider)
    await session.flush()
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="rider",
        entity_id=str(rider.id),
        action="created",
        after={"name": name, "phone": phone},
    )
    await session.commit()
    await session.refresh(rider)
    return rider


async def _latest_rider_locations(
    session: AsyncSession, *, restaurant_id: int
) -> dict[int, object]:
    """Best-effort latest ping map keyed by rider_id.

    Some deployed databases can lag schema migrations. If the rider-location
    table/query is unavailable, degrade to an empty map so the Riders screen
    still loads and shows the rider rows without live-position metadata.
    """
    from app.dispatch.models import RiderLocation

    try:
        pings = await session.scalars(
            select(RiderLocation)
            .where(RiderLocation.restaurant_id == restaurant_id)
            .order_by(RiderLocation.rider_id, RiderLocation.ts.desc())
            .distinct(RiderLocation.rider_id)
        )
    except ProgrammingError:
        return {}
    return {p.rider_id: p for p in pings}


async def list_riders(session: AsyncSession, restaurant_id: int) -> list[Rider]:
    from app.ordering.models import Order

    rows = await session.scalars(
        select(Rider).where(Rider.restaurant_id == restaurant_id).order_by(Rider.id)
    )
    riders = list(rows)

    # Per-rider delivery tallies: lifetime (all delivered) + a rolling last-24h
    # window. One grouped query, then attach to each rider for RiderOut.
    window_start = datetime.now(timezone.utc) - timedelta(hours=24)
    counts = await session.execute(
        select(
            Order.rider_id,
            func.count().label("lifetime"),
            func.count(case((Order.delivered_at >= window_start, 1))).label("today"),
        )
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status == "delivered",
            Order.rider_id.is_not(None),
        )
        .group_by(Order.rider_id)
    )
    tally = {rid: (lifetime, today) for rid, lifetime, today in counts}

    # Latest location ping per rider (DISTINCT ON keeps only the newest row per
    # rider) so the dashboard can show a live-tracking dot + "seen X ago".
    latest = await _latest_rider_locations(session, restaurant_id=restaurant_id)

    for rider in riders:
        lifetime, today = tally.get(rider.id, (0, 0))
        rider.delivered_lifetime = lifetime
        rider.delivered_24h = today
        ping = latest.get(rider.id)
        rider.last_lat = ping.latitude if ping else None
        rider.last_lng = ping.longitude if ping else None
        rider.last_location_at = ping.ts if ping else None
    return riders


async def latest_rider_location(
    session: AsyncSession, *, restaurant_id: int, rider_id: int
):
    """Most recent location ping for one rider (tenant-scoped), or None.

    Returns a lightweight object with ``lat``/``lng``/``ts`` for the live-tracking
    map's polling endpoint. ``None`` distinguishes "no ping yet" from "no rider"
    (the router turns a missing rider into a 404)."""
    from app.dispatch.models import RiderLocation

    rider = await session.get(Rider, rider_id)
    if rider is None or rider.restaurant_id != restaurant_id:
        return False  # signal "rider not found" to the router
    try:
        ping = await session.scalar(
            select(RiderLocation)
            .where(RiderLocation.rider_id == rider_id)
            .order_by(RiderLocation.ts.desc())
            .limit(1)
        )
    except ProgrammingError:
        return None
    if ping is None:
        return None
    return {"lat": ping.latitude, "lng": ping.longitude, "ts": ping.ts}


async def set_rider_status(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider_id: int,
    status: str,
) -> Rider | None:
    rider = await session.get(Rider, rider_id)
    if rider is None or rider.restaurant_id != restaurant_id:
        return None
    before = {"status": rider.status}
    rider.status = status
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="rider",
        entity_id=str(rider.id),
        action="status_changed",
        before=before,
        after={"status": status},
    )
    await session.commit()
    await session.refresh(rider)
    return rider


async def set_rider_on_duty(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider_id: int,
    on_duty: bool,
) -> Rider | None:
    """Manager-side write of the SHARED duty flag (the same ``on_duty`` the rider sets
    in their app). One control for both sides: a rider gets new orders only while
    on_duty is True. Turning a rider ON also clears a legacy ``off_shift`` status so
    they're immediately dispatchable; turning OFF leaves the operational status alone
    (dispatch is blocked by on_duty)."""
    rider = await session.get(Rider, rider_id)
    if rider is None or rider.restaurant_id != restaurant_id:
        return None
    if rider.status == "deactivated":
        # Duty is meaningless for a removed rider — reactivate via status first.
        return rider
    before = {"on_duty": rider.on_duty, "status": rider.status}
    rider.on_duty = on_duty
    if on_duty and rider.status == "off_shift":
        rider.status = "available"
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="rider",
        entity_id=str(rider.id),
        action="duty_changed",
        before=before,
        after={"on_duty": rider.on_duty, "status": rider.status},
    )
    await session.commit()
    await session.refresh(rider)
    return rider


async def update_rider_profile(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider_id: int,
    name: str | None = None,
    phone: str | None = None,
) -> Rider | None:
    rider = await session.get(Rider, rider_id)
    if rider is None or rider.restaurant_id != restaurant_id:
        return None
    before = {"name": rider.name, "phone": rider.phone}
    if phone is not None and phone != rider.phone:
        dup = await session.scalar(
            select(Rider).where(
                Rider.restaurant_id == restaurant_id,
                Rider.phone == phone,
                Rider.id != rider.id,
            )
        )
        if dup:
            raise DuplicatePhoneError("rider phone already registered")
        rider.phone = phone
    if name is not None:
        rider.name = name
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="rider",
        entity_id=str(rider.id),
        action="profile_updated",
        before=before,
        after={"name": rider.name, "phone": rider.phone},
    )
    await session.commit()
    await session.refresh(rider)
    return rider


async def delete_rider(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider_id: int,
) -> bool:
    rider = await session.get(Rider, rider_id)
    if rider is None or rider.restaurant_id != restaurant_id:
        return False

    # Preserve financial history: a rider holding COD cash records or shift
    # reconciliations must not be hard-deleted — deactivate instead.
    from app.cod.models import CodCollection, RiderShiftReconciliation

    has_money = await session.scalar(
        select(CodCollection.id).where(CodCollection.rider_id == rider_id).limit(1)
    ) or await session.scalar(
        select(RiderShiftReconciliation.id)
        .where(RiderShiftReconciliation.rider_id == rider_id)
        .limit(1)
    )
    if has_money:
        raise RiderHasHistoryError(
            "This rider has payment records on file — deactivate them instead of removing."
        )

    # Detach orders so their records survive: drop the rider link, and return any
    # in-flight delivery to the dispatch pool (back to 'ready', unassigned).
    from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation
    from app.ordering.fsm import OrderStatus
    from app.ordering.models import Order

    _active = {
        str(OrderStatus.ASSIGNED), str(OrderStatus.PICKED_UP), str(OrderStatus.ARRIVING),
    }
    orders = (
        await session.scalars(select(Order).where(Order.rider_id == rider_id))
    ).all()
    for o in orders:
        if str(o.status) in _active:
            o.status = OrderStatus.READY  # recovery: re-enters dispatch
        o.rider_id = None

    # Remove the rider's operational rows (no financial value).
    await session.execute(delete(RiderLocation).where(RiderLocation.rider_id == rider_id))
    await session.execute(delete(Assignment).where(Assignment.rider_id == rider_id))
    batch_ids = (
        await session.scalars(select(Batch.id).where(Batch.rider_id == rider_id))
    ).all()
    if batch_ids:
        await session.execute(delete(BatchOrder).where(BatchOrder.batch_id.in_(batch_ids)))
        await session.execute(delete(Batch).where(Batch.id.in_(batch_ids)))

    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="rider",
        entity_id=str(rider.id),
        action="deleted",
        before={"name": rider.name, "phone": rider.phone},
    )
    await session.delete(rider)
    await session.commit()
    return True


async def update_profile(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    name: str,
    lat: float | None = None,
    lng: float | None = None,
) -> Restaurant:
    before = {"name": restaurant.name, "lat": restaurant.lat, "lng": restaurant.lng}
    restaurant.name = name
    if lat is not None:
        restaurant.lat = lat
    if lng is not None:
        restaurant.lng = lng
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant.id,
        entity="restaurant",
        entity_id=str(restaurant.id),
        action="profile_changed",
        before=before,
        after={"name": name, "lat": restaurant.lat, "lng": restaurant.lng},
    )
    await session.commit()
    await session.refresh(restaurant)
    return restaurant


async def update_settings(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    changes: dict,
) -> Restaurant:
    before = {k: restaurant.settings.get(k) for k in changes}
    restaurant.settings = {**restaurant.settings, **changes}
    flag_modified(restaurant, "settings")
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant.id,
        entity="restaurant",
        entity_id=str(restaurant.id),
        action="settings_changed",
        before=before,
        after=changes,
    )
    await session.commit()
    await session.refresh(restaurant)
    return restaurant
