"""Habit drift on recurring weekly advance (spec §4.4.5)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.marketing.automations import advance_recurring_state
from app.marketing.models import RecurringMessageState
from app.ordering.models import Customer, Order
from app.ordering.service import recompute_customer_stats


async def test_advance_recurring_weekly_recomputes_usual_send_from_habits(
    db_session, restaurant
):
    """Weekly phase must refresh usual_send_local_time from usual_order_times."""
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000905", name="Drift")
    db_session.add(cust)
    await db_session.flush()
    # Three Friday lunch orders at 12:00 Dubai (08:00 UTC)
    db_session.add_all([
        Order(
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            order_number=f"R-D{i}",
            status="delivered",
            created_at=datetime(2026, 6, 5 + i * 7, 8, 0),
        )
        for i in range(3)
    ])
    await db_session.flush()
    await recompute_customer_stats(db_session, cust.id)
    await db_session.refresh(cust)
    assert cust.usual_order_times.get("4") is not None

    now = datetime(2026, 6, 27, 7, 30, tzinfo=timezone.utc)  # Saturday Dubai
    state = RecurringMessageState(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        phase="weekly",
        weekday=4,  # Friday recurring
        usual_send_local_time="10:00",  # stale
        next_send_at=now - timedelta(minutes=1),
    )
    db_session.add(state)
    await db_session.flush()

    await advance_recurring_state(
        db_session, state=state, lead_minutes=15, now_utc=now
    )
    await db_session.refresh(state)

    # 12:00 Dubai usual → send at 11:45, not the stale 10:00
    assert state.usual_send_local_time == "12:00"
    local_send = state.next_send_at.astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Dubai")
    )
    assert local_send.hour == 11 and local_send.minute == 45