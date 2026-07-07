from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_duplicate_order_endpoint(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Falafel",
        price_aed=Decimal("12.00"), is_available=True, name_normalized="falafel",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000871", name="Router Dup")
    db_session.add(cust)
    await db_session.flush()
    original = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="RDUP-0001",
        status="delivered", subtotal=Decimal("12.00"), total=Decimal("12.00"),
    )
    db_session.add(original)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=original.id, dish_id=dish.id, dish_number=1, dish_name="Falafel",
        price_aed=Decimal("12.00"), qty=1,
    ))
    await db_session.commit()

    resp = await client.post(f"/api/v1/orders/{original.id}/duplicate", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "draft"
    assert resp.json()["id"] != original.id
    assert resp.json()["total_aed"] == "12.00"
