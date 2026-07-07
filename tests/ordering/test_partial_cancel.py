from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.audit.models import AuditLog
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order, OrderItem


async def _seed_confirmed_order_two_items(db_session, restaurant_id: int) -> Order:
    """Seed a confirmed order with two line items. Returns the order."""
    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish1 = Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=110, name="Chicken Biryani",
        price_aed=Decimal("22.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    )
    dish2 = Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=111, name="Lemon Mint",
        price_aed=Decimal("12.00"), category="Drinks",
        is_available=True, name_normalized="lemon mint",
    )
    db_session.add_all([dish1, dish2])
    await db_session.flush()

    customer = Customer(
        restaurant_id=restaurant_id, phone="+971501230199", name="Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=restaurant_id, customer_id=customer.id,
        order_number="R1-PCX1", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("5.00"),
        subtotal=Decimal("34.00"), total=Decimal("39.00"),
        sla_confirmed_at=now, sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.flush()

    item1 = OrderItem(
        order_id=order.id, dish_id=dish1.id,
        dish_number=110, dish_name="Chicken Biryani",
        price_aed=Decimal("22.00"), qty=1,
    )
    item2 = OrderItem(
        order_id=order.id, dish_id=dish2.id,
        dish_number=111, dish_name="Lemon Mint",
        price_aed=Decimal("12.00"), qty=1,
    )
    db_session.add_all([item1, item2])
    await db_session.commit()
    await db_session.refresh(order)
    return order


async def _order_items(db_session, order_id: int) -> list[OrderItem]:
    return list(
        (await db_session.scalars(select(OrderItem).where(OrderItem.order_id == order_id))).all()
    )


# ---------------------------------------------------------------------------
# Service-level tests
# ---------------------------------------------------------------------------


async def test_cancel_order_item_marks_cancelled_and_recomputes_totals(db_session, restaurant):
    from app.ordering.service import cancel_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)
    target = items[0]

    cancelled_item = await cancel_order_item(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        order_item_id=target.id,
        reason="customer changed mind",
        actor="manager",
    )
    await db_session.commit()
    await db_session.refresh(order)

    assert cancelled_item.cancelled is True
    assert cancelled_item.cancelled_reason == "customer changed mind"

    remaining_subtotal = sum(
        i.price_aed * i.qty for i in items if i.id != target.id
    )
    assert order.subtotal == remaining_subtotal
    assert order.total == remaining_subtotal + order.delivery_fee_aed


async def test_cancel_order_item_produces_audit_log(db_session, restaurant):
    from app.ordering.service import cancel_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)

    await cancel_order_item(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        order_item_id=items[0].id,
        reason=None,
        actor="manager",
    )
    await db_session.commit()

    logs = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(r.action == "order_item_cancelled" for r in logs)


async def test_cancel_order_item_blocked_at_ready(db_session, restaurant):
    from app.ordering.service import cancel_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)
    order.status = OrderStatus.READY
    await db_session.commit()

    with pytest.raises(ValueError, match="not allowed"):
        await cancel_order_item(
            db_session,
            restaurant_id=restaurant.id,
            order_id=order.id,
            order_item_id=items[0].id,
            reason=None,
            actor="manager",
        )


async def test_cancel_order_item_wrong_tenant_raises(db_session, restaurant):
    from app.identity.models import Restaurant
    from app.ordering.service import cancel_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)

    other = Restaurant(
        name="Other Restaurant", phone="+97141234599", password_hash="x",
        lat=25.1, lng=55.1,
    )
    db_session.add(other)
    await db_session.flush()

    with pytest.raises(ValueError, match="not found"):
        await cancel_order_item(
            db_session,
            restaurant_id=other.id,
            order_id=order.id,
            order_item_id=items[0].id,
            reason=None,
            actor="manager",
        )


async def test_cancel_order_item_unknown_item_raises(db_session, restaurant):
    from app.ordering.service import cancel_order_item

    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)

    with pytest.raises(ValueError, match="not found"):
        await cancel_order_item(
            db_session,
            restaurant_id=restaurant.id,
            order_id=order.id,
            order_item_id=999999,
            reason=None,
            actor="manager",
        )


# ---------------------------------------------------------------------------
# Router-level tests (RBAC)
# ---------------------------------------------------------------------------


async def test_non_manager_staff_cannot_cancel_order_item(client, auth_headers, db_session):
    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)

    staff_resp = await client.post(
        "/api/v1/staff", json={"name": "Cashier Nour", "role": "cashier", "pin": "4321"},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "4321"})
    staff_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        f"/api/v1/orders/{order.id}/items/{items[0].id}/cancel", headers=staff_headers
    )
    assert resp.status_code == 403


async def test_manager_role_staff_can_cancel_order_item(client, auth_headers, db_session):
    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)

    staff_resp = await client.post(
        "/api/v1/staff", json={"name": "Manager Fatima", "role": "manager", "pin": "5432"},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "5432"})
    staff_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(
        f"/api/v1/orders/{order.id}/items/{items[0].id}/cancel",
        json={"reason": "out of stock"},
        headers=staff_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    cancelled = [i for i in body["items"] if i.get("cancelled")]
    assert len(cancelled) == 1
    assert cancelled[0]["cancelled_reason"] == "out of stock"


async def test_cancel_order_item_at_ready_returns_422(client, auth_headers, db_session):
    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    order = await _seed_confirmed_order_two_items(db_session, restaurant.id)
    items = await _order_items(db_session, order.id)
    order.status = OrderStatus.READY
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/items/{items[0].id}/cancel", headers=auth_headers
    )
    assert resp.status_code == 422
