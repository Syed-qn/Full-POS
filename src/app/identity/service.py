# src/app/identity/service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.audit import record_audit
from app.identity.auth import hash_password
from app.identity.models import Restaurant, Rider


class DuplicatePhoneError(Exception):
    pass


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
