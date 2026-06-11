"""Order cancellation endpoint (POST /api/v1/orders/{id}/cancel).

Covers the spec rules: pre-cook cancel → 'cancelled'; cooking (preparing) →
'on_resale' with a resale copy; post-kitchen states reject with 422.
"""
from decimal import Decimal

from sqlalchemy import select

from app.menu.models import Dish, Menu
from app.ordering.models import Order


def _token(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token

    return create_access_token(restaurant_id=restaurant_id)


async def _seed_menu(db_session, restaurant_id: int) -> Menu:
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id,
        dish_number=101, name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()
    return menu


async def _make_order(db_session, restaurant_id: int, phone: str) -> Order:
    from app.ordering.service import create_manual_order

    menu = await _seed_menu(db_session, restaurant_id)
    dish = await db_session.scalar(select(Dish).where(Dish.menu_id == menu.id))
    order = await create_manual_order(
        db_session,
        restaurant_id=restaurant_id,
        customer_phone=phone,
        customer_name="Test Buyer",
        items=[{"dish_id": dish.id, "qty": 1, "notes": None}],
        apt_room="1A",
        building="Tower",
        receiver_name="Test Buyer",
        address_notes=None,
        delivery_fee_aed=Decimal("0.00"),
    )
    await db_session.commit()
    return order


async def test_cancel_confirmed_order_returns_cancelled(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993001")
    assert order.status == "confirmed"

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        json={"reason": "customer changed mind"},
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"

    await db_session.refresh(order)
    assert order.status == "cancelled"
    assert order.cancelled_at is not None
    assert order.cancellation_reason == "customer changed mind"


async def test_cancel_preparing_order_goes_to_resale(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993002")
    order.status = "preparing"  # already cooking
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "on_resale"

    # a resale copy must exist, linked back to the cancelled original
    resale = await db_session.scalar(
        select(Order).where(Order.resale_of_order_id == order.id)
    )
    assert resale is not None
    assert resale.status == "on_resale"


async def test_cancel_ready_order_is_422(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993003")
    order.status = "ready"  # left the kitchen — no longer cancellable
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{order.id}/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 422

    await db_session.refresh(order)
    assert order.status == "ready"  # unchanged


async def test_cancel_unknown_order_is_404(client, restaurant):
    resp = await client.post(
        "/api/v1/orders/999999/cancel",
        headers={"Authorization": f"Bearer {_token(restaurant.id)}"},
    )
    assert resp.status_code == 404


async def test_cancel_requires_auth(client, db_session, restaurant):
    order = await _make_order(db_session, restaurant.id, "+971509993004")
    resp = await client.post(f"/api/v1/orders/{order.id}/cancel")
    assert resp.status_code == 401
