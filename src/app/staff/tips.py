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
            Order.is_training.is_(False),
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


async def tips_by_staff(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date,
) -> dict[int, Decimal]:
    """Tips attributed to specific servers via Order.tip_staff_id (server-attributed).

    Falls back to order.staff_id when tip_staff_id is null so POS orders still count.
    """
    from app.ordering.models import Order
    from app.payments.models import PaymentTransaction

    range_start = datetime.combine(start_date, time.min)
    range_end = datetime.combine(end_date, time.max)

    rows = (
        await session.execute(
            select(
                Order.tip_staff_id,
                Order.staff_id,
                PaymentTransaction.tip_aed,
            )
            .join(Order, Order.id == PaymentTransaction.order_id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.created_at >= range_start,
                Order.created_at <= range_end,
                Order.is_training.is_(False),
                PaymentTransaction.tip_aed > 0,
            )
        )
    ).all()

    out: dict[int, Decimal] = {}
    for tip_staff_id, staff_id, tip_aed in rows:
        sid = tip_staff_id or staff_id
        if sid is None:
            continue
        out[sid] = (out.get(sid, Decimal("0.00")) + Decimal(str(tip_aed))).quantize(
            Decimal("0.01")
        )
    return out


async def attribute_tip_to_staff(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    staff_id: int,
) -> None:
    from app.ordering.models import Order

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError("order not found")
    order.tip_staff_id = staff_id
    await session.flush()
