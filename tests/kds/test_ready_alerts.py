"""GET /kds/ready-alerts — creator-only "your order is ready" feed for the
waiter/cashier top-bar bell."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest


async def _auth_restaurant(db_session):
    """The tenant the owner token (auth_headers) belongs to — staff and orders
    must live here, not the separate `restaurant` fixture, or the endpoint's
    tenant filter drops them."""
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


async def _cashier_headers(client, auth_headers, name, pin):
    staff_resp = await client.post(
        "/api/v1/staff",
        json={"name": name, "role": "cashier", "pin": pin},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post(
        "/api/v1/staff/login", json={"staff_id": staff_id, "pin": pin}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}, staff_id


async def _order_with_items(
    db_session, restaurant, *, staff_id, number, statuses, token=None, order_type="takeaway"
):
    """Create an order owned by ``staff_id`` with one OrderItem per entry in
    ``statuses`` ((kitchen_status, minutes_ago) tuples; minutes_ago sets bumped_at)."""
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    menu = Menu(restaurant_id=restaurant.id, version=number, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), category="Grills", is_available=True,
        name_normalized="kebab",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone=f"+9715000{number:05d}", name="T")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number=f"RA-{number:04d}",
        status="confirmed",
        subtotal=Decimal("20.00"),
        total=Decimal("20.00"),
        staff_id=staff_id,
        order_type=order_type,
        daily_token=token,
    )
    db_session.add(order)
    await db_session.flush()
    for kstatus, mins_ago in statuses:
        db_session.add(
            OrderItem(
                order_id=order.id,
                dish_id=dish.id,
                dish_number=1,
                dish_name="Kebab",
                price_aed=Decimal("20.00"),
                qty=1,
                kitchen_status=kstatus,
                bumped_at=(
                    datetime.utcnow() - timedelta(minutes=mins_ago)
                    if kstatus == "ready"
                    else None
                ),
            )
        )
    await db_session.commit()
    return order


@pytest.mark.anyio
async def test_ready_alerts_creator_only_and_whole_order(
    client, auth_headers, db_session
):
    restaurant = await _auth_restaurant(db_session)
    mine_headers, my_id = await _cashier_headers(client, auth_headers, "Cashier A", "4111")
    _, other_id = await _cashier_headers(client, auth_headers, "Cashier B", "4222")

    # Fully-bumped order I created → should alert.
    ready = await _order_with_items(
        db_session, restaurant, staff_id=my_id, number=1,
        statuses=[("ready", 2), ("ready", 1)], token=7,
    )
    # Partially-bumped order I created → NOT ready yet.
    await _order_with_items(
        db_session, restaurant, staff_id=my_id, number=2,
        statuses=[("ready", 2), ("received", 0)], token=8,
    )
    # Fully-bumped order OWNED BY SOMEONE ELSE → must not leak to me.
    await _order_with_items(
        db_session, restaurant, staff_id=other_id, number=3,
        statuses=[("ready", 1)], token=9,
    )

    resp = await client.get(
        "/api/v1/kds/ready-alerts?since=2000-01-01T00:00:00", headers=mine_headers
    )
    assert resp.status_code == 200
    rows = resp.json()
    ids = {r["order_id"] for r in rows}
    assert ids == {ready.id}
    assert rows[0]["daily_token"] == 7
    assert rows[0]["order_type"] == "takeaway"


@pytest.mark.anyio
async def test_ready_alerts_since_watermark_excludes_older(
    client, auth_headers, db_session
):
    restaurant = await _auth_restaurant(db_session)
    mine_headers, my_id = await _cashier_headers(client, auth_headers, "Cashier C", "4333")
    # Ready 10 minutes ago.
    await _order_with_items(
        db_session, restaurant, staff_id=my_id, number=11,
        statuses=[("ready", 10)], token=1,
    )
    # Watermark set to 5 minutes ago → the 10-min-old ready is already seen.
    since = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    resp = await client.get(
        f"/api/v1/kds/ready-alerts?since={since}", headers=mine_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.anyio
async def test_ready_alerts_owner_token_is_empty(client, auth_headers, db_session, restaurant):
    # Manager/owner token carries no staff id → empty feed (they use the manager
    # alert center instead).
    resp = await client.get(
        "/api/v1/kds/ready-alerts?since=2000-01-01T00:00:00", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == []
