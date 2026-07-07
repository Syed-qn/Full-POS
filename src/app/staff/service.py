from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.staff.models import ClockEvent


class AlreadyClockedInError(Exception):
    pass


class NotClockedInError(Exception):
    pass


async def _last_event(session: AsyncSession, *, staff_id: int, restaurant_id: int) -> ClockEvent | None:
    return await session.scalar(
        select(ClockEvent)
        .where(ClockEvent.staff_id == staff_id, ClockEvent.restaurant_id == restaurant_id)
        .order_by(ClockEvent.at.desc())
        .limit(1)
    )


async def clock_in(session: AsyncSession, *, staff_id: int, restaurant_id: int, at: datetime) -> ClockEvent:
    last = await _last_event(session, staff_id=staff_id, restaurant_id=restaurant_id)
    if last is not None and last.type == "clock_in":
        raise AlreadyClockedInError(f"staff {staff_id} is already clocked in")
    event = ClockEvent(restaurant_id=restaurant_id, staff_id=staff_id, type="clock_in", at=at)
    session.add(event)
    await session.flush()
    return event


async def clock_out(session: AsyncSession, *, staff_id: int, restaurant_id: int, at: datetime) -> ClockEvent:
    last = await _last_event(session, staff_id=staff_id, restaurant_id=restaurant_id)
    if last is None or last.type != "clock_in":
        raise NotClockedInError(f"staff {staff_id} is not clocked in")
    event = ClockEvent(restaurant_id=restaurant_id, staff_id=staff_id, type="clock_out", at=at)
    session.add(event)
    await session.flush()
    return event


async def compute_hours(session: AsyncSession, *, staff_id: int, restaurant_id: int, target_date: date) -> float:
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)
    events = (await session.scalars(
        select(ClockEvent)
        .where(
            ClockEvent.staff_id == staff_id, ClockEvent.restaurant_id == restaurant_id,
            ClockEvent.at >= day_start, ClockEvent.at <= day_end,
        )
        .order_by(ClockEvent.at)
    )).all()

    total_seconds = 0.0
    open_in: datetime | None = None
    for event in events:
        at = event.at.replace(tzinfo=None) if event.at.tzinfo else event.at
        if event.type == "clock_in":
            open_in = at
        elif event.type == "clock_out" and open_in is not None:
            total_seconds += (at - open_in).total_seconds()
            open_in = None
    return total_seconds / 3600.0


async def compute_sales(session: AsyncSession, *, staff_id: int, restaurant_id: int, target_date: date) -> Decimal:
    from app.ordering.models import Order

    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)
    orders = (await session.scalars(
        select(Order).where(
            Order.staff_id == staff_id, Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
        )
    )).all()
    return sum((o.total for o in orders), Decimal("0.00"))
