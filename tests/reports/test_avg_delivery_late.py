"""Late-delivery accounting in the owner report must never contradict the
average it shows. Orders imported/back-filled without a stamped ``Order.late``
flag (NULL) used to count as on-time, so a batch of 4-hour deliveries reported
"0% late" next to a 200-min average. The report now falls back to the actual
duration vs the customer SLA whenever the flag is missing.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.reports.extended import average_delivery_time


async def _delivered(db_session, restaurant, *, order_number, minutes, late):
    from app.ordering.models import Customer, Order

    cust = Customer(restaurant_id=restaurant.id, phone=f"+97150{order_number}", name="Cust")
    db_session.add(cust)
    await db_session.flush()
    base = datetime.now(timezone.utc) - timedelta(days=1)
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number=order_number,
        status="delivered",
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        sla_confirmed_at=base,
        delivered_at=base + timedelta(minutes=minutes),
        late=late,
    )
    db_session.add(order)
    await db_session.flush()
    return order


@pytest.mark.anyio
async def test_null_late_flag_falls_back_to_duration_vs_sla(db_session, restaurant):
    # Two orders way over the 40-min SLA but with an UNSET late flag (imported
    # data), plus one genuinely quick order. Old behaviour: 0% late. Correct: the
    # two slow ones are late by duration.
    await _delivered(db_session, restaurant, order_number="AD-0001", minutes=230, late=None)
    await _delivered(db_session, restaurant, order_number="AD-0002", minutes=90, late=None)
    await _delivered(db_session, restaurant, order_number="AD-0003", minutes=12, late=None)
    await db_session.commit()

    today = date.today()
    result = await average_delivery_time(
        db_session, restaurant_id=restaurant.id, start_date=today - timedelta(days=2), end_date=today
    )

    assert result["delivery_count"] == 3
    assert result["late_count"] == 2
    assert result["late_pct"] == pytest.approx(66.67, abs=0.01)


@pytest.mark.anyio
async def test_explicit_late_flag_is_respected_over_duration(db_session, restaurant):
    # A stamped flag wins: a quick delivery explicitly marked late still counts,
    # and a slow one explicitly marked on-time (e.g. disclosed weather delay)
    # does not — the duration fallback only fills NULLs.
    await _delivered(db_session, restaurant, order_number="AD-0101", minutes=10, late=True)
    await _delivered(db_session, restaurant, order_number="AD-0102", minutes=300, late=False)
    await db_session.commit()

    today = date.today()
    result = await average_delivery_time(
        db_session, restaurant_id=restaurant.id, start_date=today - timedelta(days=2), end_date=today
    )

    assert result["delivery_count"] == 2
    assert result["late_count"] == 1  # only the explicitly-late one
