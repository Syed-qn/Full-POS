"""After a DB reset, order/order_item ids get reused while the append-only
audit_log keeps the old rows. The timeline must NOT surface a previous order's
events for a recycled id — it is bounded to the order's own creation time."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest


async def _restaurant(db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


@pytest.mark.anyio
async def test_timeline_excludes_recycled_id_ghost_events(client, auth_headers, db_session):
    from app.audit.models import AuditLog
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await _restaurant(db_session)
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Cheesecake",
        price_aed=Decimal("19.00"), category="Dessert", is_available=True,
        name_normalized="cheesecake",
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000321", name="T")
    db_session.add_all([dish, cust])
    await db_session.flush()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="RC-0001",
        status="preparing", subtotal=Decimal("19.00"), total=Decimal("19.00"),
        order_type="takeaway", daily_token=17,
    )
    db_session.add(order)
    await db_session.flush()
    order.created_at = now
    item = OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Cheesecake",
        price_aed=Decimal("19.00"), qty=1, kitchen_status="received",
    )
    db_session.add(item)
    await db_session.flush()

    # A GHOST row from a PREVIOUS order that reused this order_item id, 4 days ago.
    ghost = AuditLog(
        restaurant_id=restaurant.id, entity="order_item", entity_id=str(item.id),
        action="bump", actor="kitchen", before=None, after={},
    )
    # A REAL row for this order, at creation time.
    real = AuditLog(
        restaurant_id=restaurant.id, entity="order", entity_id=str(order.id),
        action="pos_order_created", actor="manager", before=None, after={},
    )
    db_session.add_all([ghost, real])
    await db_session.flush()
    ghost.created_at = now - timedelta(days=4)
    real.created_at = now
    await db_session.commit()

    resp = await client.get(
        f"/api/v1/orders/{order.id}/detail?include=timeline", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    actions = [e["action"] for e in resp.json()["timeline"]]
    assert "pos_order_created" in actions          # this order's real event kept
    assert "bump" not in actions                    # recycled-id ghost dropped
