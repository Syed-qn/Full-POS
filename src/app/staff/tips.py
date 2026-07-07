from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.staff.models import ClockEvent


async def distribute_tip_pool(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date,
) -> dict[int, Decimal]:
    """Sum tips on delivered orders in [start_date, end_date] (inclusive) and split
    evenly across staff who clocked in at any point during that window. Equal split
    is the simplest correct default — no weighting by hours worked or sales."""
    from app.ordering.models import Order
    from app.payments.models import PaymentTransaction

    range_start = datetime.combine(start_date, time.min)
    range_end = datetime.combine(end_date, time.max)

    tip_rows = (await session.scalars(
        select(PaymentTransaction.tip_aed)
        .join(Order, Order.id == PaymentTransaction.order_id)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status == "delivered",
            Order.delivered_at >= range_start,
            Order.delivered_at <= range_end,
        )
    )).all()
    total_tips = sum(tip_rows, Decimal("0.00"))

    if total_tips <= Decimal("0.00"):
        return {}

    staff_ids = (await session.scalars(
        select(ClockEvent.staff_id)
        .where(
            ClockEvent.restaurant_id == restaurant_id,
            ClockEvent.type == "clock_in",
            ClockEvent.at >= range_start,
            ClockEvent.at <= range_end,
        )
        .distinct()
    )).all()

    if not staff_ids:
        return {}

    share = (total_tips / len(staff_ids)).quantize(Decimal("0.01"))
    return {staff_id: share for staff_id in staff_ids}
