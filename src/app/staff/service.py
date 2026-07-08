from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.staff.models import ClockEvent


class AlreadyClockedInError(Exception):
    pass


class NotClockedInError(Exception):
    pass


class AlreadyOnBreakError(Exception):
    pass


class NotOnBreakError(Exception):
    pass


OVERTIME_THRESHOLD_HOURS = 8.0


async def _last_event(session: AsyncSession, *, staff_id: int, restaurant_id: int) -> ClockEvent | None:
    return await session.scalar(
        select(ClockEvent)
        .where(ClockEvent.staff_id == staff_id, ClockEvent.restaurant_id == restaurant_id)
        .order_by(ClockEvent.at.desc())
        .limit(1)
    )


async def clock_in(session: AsyncSession, *, staff_id: int, restaurant_id: int, at: datetime) -> ClockEvent:
    last = await _last_event(session, staff_id=staff_id, restaurant_id=restaurant_id)
    if last is not None and last.type in ("clock_in", "break_start"):
        raise AlreadyClockedInError(f"staff {staff_id} is already clocked in")
    event = ClockEvent(restaurant_id=restaurant_id, staff_id=staff_id, type="clock_in", at=at)
    session.add(event)
    await session.flush()
    return event


async def clock_out(session: AsyncSession, *, staff_id: int, restaurant_id: int, at: datetime) -> ClockEvent:
    last = await _last_event(session, staff_id=staff_id, restaurant_id=restaurant_id)
    if last is None or last.type not in ("clock_in", "break_end"):
        raise NotClockedInError(f"staff {staff_id} is not clocked in")
    event = ClockEvent(restaurant_id=restaurant_id, staff_id=staff_id, type="clock_out", at=at)
    session.add(event)
    await session.flush()
    return event


async def start_break(session: AsyncSession, *, staff_id: int, restaurant_id: int, at: datetime) -> ClockEvent:
    last = await _last_event(session, staff_id=staff_id, restaurant_id=restaurant_id)
    if last is None or last.type == "clock_out":
        raise NotClockedInError(f"staff {staff_id} is not clocked in")
    if last.type == "break_start":
        raise AlreadyOnBreakError(f"staff {staff_id} is already on break")
    event = ClockEvent(restaurant_id=restaurant_id, staff_id=staff_id, type="break_start", at=at)
    session.add(event)
    await session.flush()
    return event


async def end_break(session: AsyncSession, *, staff_id: int, restaurant_id: int, at: datetime) -> ClockEvent:
    last = await _last_event(session, staff_id=staff_id, restaurant_id=restaurant_id)
    if last is None or last.type != "break_start":
        raise NotOnBreakError(f"staff {staff_id} is not on break")
    event = ClockEvent(restaurant_id=restaurant_id, staff_id=staff_id, type="break_end", at=at)
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
    break_seconds = 0.0
    open_in: datetime | None = None
    open_break: datetime | None = None
    for event in events:
        at = event.at.replace(tzinfo=None) if event.at.tzinfo else event.at
        if event.type == "clock_in":
            open_in = at
        elif event.type == "clock_out" and open_in is not None:
            total_seconds += (at - open_in).total_seconds()
            open_in = None
        elif event.type == "break_start":
            open_break = at
        elif event.type == "break_end" and open_break is not None:
            break_seconds += (at - open_break).total_seconds()
            open_break = None
    return (total_seconds - break_seconds) / 3600.0


def compute_overtime_hours(worked_hours: float) -> float:
    return max(0.0, worked_hours - OVERTIME_THRESHOLD_HOURS)


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
