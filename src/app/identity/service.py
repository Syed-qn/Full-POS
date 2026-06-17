# src/app/identity/service.py
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.audit import record_audit
from app.identity.auth import hash_password
from app.identity.models import Restaurant, Rider


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


async def list_riders(session: AsyncSession, restaurant_id: int) -> list[Rider]:
    rows = await session.scalars(
        select(Rider).where(Rider.restaurant_id == restaurant_id).order_by(Rider.id)
    )
    return list(rows)


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
