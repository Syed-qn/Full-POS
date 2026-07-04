"""Per-weekday, recency-weighted order-time habits (spec gap closure)."""

from datetime import datetime, timezone

from app.ordering.habits import (
    build_usual_order_times,
    habit_for_weekday,
    order_stamps_from_rows,
    predict_from_stamps,
    recency_weight,
)
from app.ordering.models import Customer, Order
from app.ordering.service import predict_order_time, recompute_customer_stats


def test_recency_weight_decays_with_age():
    assert recency_weight(0) == 1.0
    assert recency_weight(60) < recency_weight(0)
    assert recency_weight(120) < recency_weight(60)


def test_weekday_isolation_friday_lunch_not_saturday_dinner():
    """Friday noon orders must not blend with Saturday evening orders."""
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)  # Friday Dubai
    rows = [
        (datetime(2026, 6, 5, 8, 0),),   # Fri 12:00 Dubai
        (datetime(2026, 6, 12, 8, 0),),  # Fri 12:00 Dubai
        (datetime(2026, 6, 19, 8, 0),),  # Fri 12:00 Dubai
        (datetime(2026, 6, 6, 16, 0),),  # Sat 20:00 Dubai
        (datetime(2026, 6, 13, 16, 0),), # Sat 20:00 Dubai
        (datetime(2026, 6, 20, 16, 0),), # Sat 20:00 Dubai
    ]
    stamps = order_stamps_from_rows(rows, now_utc=now)
    fri = predict_from_stamps(stamps, weekday=4)  # Friday
    sat = predict_from_stamps(stamps, weekday=5)  # Saturday
    assert fri is not None and sat is not None
    assert 11 * 60 + 30 <= fri.minute_of_day <= 12 * 60 + 30
    assert 19 * 60 + 30 <= sat.minute_of_day <= 20 * 60 + 30


def test_recency_favors_recent_orders():
    """A recent shift to 13:00 should pull the Friday mean away from older 12:00 orders."""
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)
    old = datetime(2026, 3, 6, 8, 0)   # Fri 12:00 Dubai, ~110 days ago
    recent = datetime(2026, 6, 19, 9, 0)  # Fri 13:00 Dubai, ~7 days ago
    rows = [(old,), (old,), (recent,), (recent,), (recent,)]
    stamps = order_stamps_from_rows(rows, now_utc=now)
    pred = predict_from_stamps(stamps, weekday=4)
    assert pred is not None
    assert pred.minute_of_day >= 12 * 60 + 15  # pulled toward 13:00


def test_build_usual_order_times_shape():
    now = datetime(2026, 6, 26, 12, 0, tzinfo=timezone.utc)
    rows = [
        (datetime(2026, 6, 5, 8, 0),),
        (datetime(2026, 6, 12, 8, 0),),
        (datetime(2026, 6, 19, 8, 0),),
    ]
    stamps = order_stamps_from_rows(rows, now_utc=now)
    habits = build_usual_order_times(stamps, now_utc=now)
    assert "4" in habits  # Friday
    entry = habits["4"]
    assert "minute" in entry
    assert entry["order_count"] == 3
    assert 0.0 <= entry["concentration"] <= 1.0


def test_habit_for_weekday_reads_jsonb():
    stored = {"4": {"minute": 720, "order_count": 3, "concentration": 0.9}}
    pred = habit_for_weekday(stored, 4)
    assert pred is not None
    assert pred.minute_of_day == 720
    assert pred.order_count == 3
    assert habit_for_weekday(stored, 5) is None


async def test_recompute_customer_stats_populates_usual_order_times(db_session, restaurant):
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000801", name="Habit")
    db_session.add(cust)
    await db_session.flush()
    db_session.add_all([
        Order(
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            order_number=f"R-H{i}",
            status="delivered",
            created_at=datetime(2026, 6, 5 + i * 7, 8, 0),  # Fridays 12:00 Dubai
        )
        for i in range(3)
    ])
    await db_session.flush()
    await recompute_customer_stats(db_session, cust.id)
    await db_session.refresh(cust)
    assert cust.usual_order_times
    assert "4" in cust.usual_order_times
    assert cust.usual_order_times["4"]["order_count"] == 3


async def test_predict_order_time_accepts_weekday(db_session, restaurant):
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000802", name="Wd")
    db_session.add(cust)
    await db_session.flush()
    db_session.add_all([
        Order(
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            order_number="R-WF1",
            status="delivered",
            created_at=datetime(2026, 6, 5, 8, 0),  # Fri 12:00
        ),
        Order(
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            order_number="R-WS1",
            status="delivered",
            created_at=datetime(2026, 6, 6, 16, 0),  # Sat 20:00
        ),
        Order(
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            order_number="R-WF2",
            status="delivered",
            created_at=datetime(2026, 6, 12, 8, 0),  # Fri 12:00
        ),
        Order(
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            order_number="R-WF3",
            status="delivered",
            created_at=datetime(2026, 6, 19, 8, 0),  # Fri 12:00
        ),
    ])
    await db_session.flush()
    fri = await predict_order_time(db_session, cust.id, weekday=4)
    sat = await predict_order_time(db_session, cust.id, weekday=5)
    assert fri is not None and sat is not None
    assert fri.order_count == 3
    assert sat.order_count == 1
    assert 11 * 60 <= fri.minute_of_day <= 12 * 60 + 30