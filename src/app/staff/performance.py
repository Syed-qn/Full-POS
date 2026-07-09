"""Attendance + staff performance reporting."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.staff.models import ClockEvent, StaffMember, StaffMistake
from app.staff.scheduling import Shift
from app.staff.service import compute_hours, compute_overtime_hours


def _money(d: Decimal) -> Decimal:
    return Decimal(str(d)).quantize(Decimal("0.01"))


async def attendance_for_date(
    session: AsyncSession,
    *,
    restaurant_id: int,
    target_date: date,
) -> list[dict]:
    """Compare scheduled shifts vs actual clock time for a calendar day."""
    day_start = datetime.combine(target_date, time.min)
    day_end = datetime.combine(target_date, time.max)

    staff_rows = list(
        (
            await session.scalars(
                select(StaffMember).where(
                    StaffMember.restaurant_id == restaurant_id,
                    StaffMember.is_active.is_(True),
                )
            )
        ).all()
    )
    shifts = list(
        (
            await session.scalars(
                select(Shift).where(
                    Shift.restaurant_id == restaurant_id,
                    Shift.scheduled_start >= day_start,
                    Shift.scheduled_start <= day_end,
                )
            )
        ).all()
    )
    shifts_by_staff: dict[int, list[Shift]] = {}
    for sh in shifts:
        shifts_by_staff.setdefault(sh.staff_id, []).append(sh)

    out = []
    for m in staff_rows:
        worked = await compute_hours(
            session,
            staff_id=m.id,
            restaurant_id=restaurant_id,
            target_date=target_date,
        )
        scheduled_hours = 0.0
        for sh in shifts_by_staff.get(m.id, []):
            ss = sh.scheduled_start
            se = sh.scheduled_end
            if ss.tzinfo:
                ss = ss.replace(tzinfo=None)
            if se.tzinfo:
                se = se.replace(tzinfo=None)
            scheduled_hours += max(0.0, (se - ss).total_seconds() / 3600.0)

        variance = worked - scheduled_hours
        status = "off"
        if scheduled_hours > 0 and worked <= 0:
            status = "absent"
        elif scheduled_hours > 0 and worked > 0:
            status = "present"
        elif worked > 0:
            status = "unscheduled_work"

        first_in = None
        events = (
            await session.scalars(
                select(ClockEvent)
                .where(
                    ClockEvent.staff_id == m.id,
                    ClockEvent.restaurant_id == restaurant_id,
                    ClockEvent.type == "clock_in",
                    ClockEvent.at >= day_start,
                    ClockEvent.at <= day_end,
                )
                .order_by(ClockEvent.at)
                .limit(1)
            )
        ).all()
        if events:
            first_in = events[0].at.isoformat()

        out.append(
            {
                "staff_id": m.id,
                "name": m.name,
                "role": m.role,
                "scheduled_hours": round(scheduled_hours, 2),
                "worked_hours": round(worked, 2),
                "variance_hours": round(variance, 2),
                "attendance_status": status,
                "first_clock_in": first_in,
                "shifts_count": len(shifts_by_staff.get(m.id, [])),
            }
        )
    return out


async def performance_report(
    session: AsyncSession,
    *,
    restaurant_id: int,
    start_date: date,
    end_date: date,
) -> list[dict]:
    """Composite per-staff performance for the inclusive date range."""
    from app.ordering.models import Order
    from app.payments.models import PaymentTransaction

    staff_rows = list(
        (
            await session.scalars(
                select(StaffMember).where(StaffMember.restaurant_id == restaurant_id)
            )
        ).all()
    )
    range_start = datetime.combine(start_date, time.min)
    range_end = datetime.combine(end_date, time.max)

    out = []
    day = start_date
    while day <= end_date:
        # precompute nothing; loop staff then days for clarity (small staff counts)
        day += timedelta(days=1)

    for m in staff_rows:
        total_hours = 0.0
        d = start_date
        while d <= end_date:
            total_hours += await compute_hours(
                session, staff_id=m.id, restaurant_id=restaurant_id, target_date=d
            )
            d += timedelta(days=1)
        ot = compute_overtime_hours(total_hours)

        # Sales excluding training orders
        orders = (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.staff_id == m.id,
                    Order.created_at >= range_start,
                    Order.created_at <= range_end,
                    Order.is_training.is_(False),
                )
            )
        ).all()
        sales = sum((o.total for o in orders), Decimal("0.00"))
        order_count = len(orders)

        # Tips attributed to this staff
        tip_orders = (
            await session.scalars(
                select(Order.id).where(
                    Order.restaurant_id == restaurant_id,
                    Order.tip_staff_id == m.id,
                    Order.created_at >= range_start,
                    Order.created_at <= range_end,
                )
            )
        ).all()
        tip_total = Decimal("0.00")
        if tip_orders:
            tips = (
                await session.scalars(
                    select(PaymentTransaction.tip_aed).where(
                        PaymentTransaction.order_id.in_(list(tip_orders))
                    )
                )
            ).all()
            tip_total = sum(tips, Decimal("0.00"))

        mistakes = (
            await session.scalars(
                select(StaffMistake).where(
                    StaffMistake.restaurant_id == restaurant_id,
                    StaffMistake.staff_id == m.id,
                    StaffMistake.created_at >= range_start,
                    StaffMistake.created_at <= range_end,
                )
            )
        ).all()
        mistake_count = len(mistakes)
        mistake_cost = sum((x.amount_aed for x in mistakes), Decimal("0.00"))

        out.append(
            {
                "staff_id": m.id,
                "name": m.name,
                "role": m.role,
                "training_mode": bool(m.training_mode),
                "hours": round(total_hours, 2),
                "overtime_hours": round(ot, 2),
                "order_count": order_count,
                "sales_aed": str(_money(sales)),
                "tips_aed": str(_money(tip_total)),
                "mistake_count": mistake_count,
                "mistake_cost_aed": str(_money(mistake_cost)),
                "sales_per_hour_aed": str(
                    _money(sales / Decimal(str(total_hours))) if total_hours > 0 else Decimal("0")
                ),
            }
        )
    return sorted(out, key=lambda r: Decimal(r["sales_aed"]), reverse=True)
