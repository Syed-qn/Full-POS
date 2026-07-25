"""Queue token resets monthly, so the same token recurs across months. The
View Bill lookup filters orders by exact token across ALL history and returns
every match (newest first) for the date-picker to disambiguate."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest


async def _restaurant(db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


async def _order(db_session, restaurant, *, number, token, created_at):
    from app.ordering.models import Customer, Order

    cust = await db_session.scalar(
        __import__("sqlalchemy").select(Customer).where(
            Customer.restaurant_id == restaurant.id
        )
    )
    if cust is None:
        cust = Customer(restaurant_id=restaurant.id, phone="+971500000999", name="T")
        db_session.add(cust)
        await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number=number,
        status="ready", subtotal=Decimal("10.00"), total=Decimal("10.00"),
        order_type="takeaway", daily_token=token,
    )
    db_session.add(order)
    await db_session.flush()
    # created_at is server-defaulted; force it to place the row in a given month.
    order.created_at = created_at
    await db_session.flush()
    return order


@pytest.mark.anyio
async def test_token_lookup_returns_every_month(client, auth_headers, db_session):
    restaurant = await _restaurant(db_session)
    # Same token "1" in two different months, plus a different token as noise.
    june = await _order(
        db_session, restaurant, number="R9-0001", token=1,
        created_at=datetime(2026, 6, 3, 8, 0, tzinfo=timezone.utc).replace(tzinfo=None),
    )
    july = await _order(
        db_session, restaurant, number="R9-0002", token=1,
        created_at=datetime(2026, 7, 3, 8, 0, tzinfo=timezone.utc).replace(tzinfo=None),
    )
    await _order(
        db_session, restaurant, number="R9-0003", token=2,
        created_at=datetime(2026, 7, 4, 8, 0, tzinfo=timezone.utc).replace(tzinfo=None),
    )
    await db_session.commit()

    resp = await client.get("/api/v1/orders?token=1&preview_batch=false", headers=auth_headers)
    assert resp.status_code == 200
    ids = [o["id"] for o in resp.json()]
    # Both token-1 bills returned; the token-2 bill excluded.
    assert set(ids) == {june.id, july.id}
    # Newest first, so the picker lists the most recent month at the top.
    assert ids[0] == july.id


@pytest.mark.anyio
async def test_token_reset_is_monthly(client, auth_headers, db_session):
    """Two orders created in the same Dubai month share the running counter;
    a fresh month starts back at 1. Verified via the allocation query window by
    seeding rows in the current month and checking the next token continues."""
    from app.ordering.service import allocate_daily_token
    from zoneinfo import ZoneInfo

    from app.ordering.models import Customer, Order

    restaurant = await _restaurant(db_session)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000888", name="T")
    db_session.add(cust)
    await db_session.flush()

    now_dubai = datetime.now(ZoneInfo("Asia/Dubai"))
    this_month = now_dubai.replace(day=15, hour=12).astimezone(timezone.utc).replace(tzinfo=None)
    # Prior month, same token 5 — must NOT influence this month's next token.
    prev = now_dubai.replace(day=1) - timedelta(days=5)
    last_month = prev.replace(hour=12).astimezone(timezone.utc).replace(tzinfo=None)

    for number, tok, ts in [
        ("RM-0001", 5, last_month),
        ("RM-0002", 1, this_month),
        ("RM-0003", 2, this_month),
    ]:
        o = Order(
            restaurant_id=restaurant.id, customer_id=cust.id, order_number=number,
            status="ready", subtotal=Decimal("1.00"), total=Decimal("1.00"),
            order_type="takeaway", daily_token=tok,
        )
        db_session.add(o)
        await db_session.flush()
        o.created_at = ts
        await db_session.flush()

    # Highest THIS month is 2 -> next is 3 (last month's 5 is ignored).
    assert await allocate_daily_token(db_session, restaurant.id) == 3
