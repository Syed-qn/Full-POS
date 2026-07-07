import pytest


@pytest.mark.anyio
async def test_trn_settable_via_settings_patch(client, auth_headers):
    resp = await client.patch(
        "/api/v1/settings", json={"trn": "100123456700003"}, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["settings"]["trn"] == "100123456700003"


@pytest.mark.anyio
async def test_trn_feeds_tax_invoice(client, auth_headers, db_session):
    from decimal import Decimal
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    await client.patch("/api/v1/settings", json={"trn": "100987654300003"}, headers=auth_headers)

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    await db_session.refresh(restaurant)
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), is_available=True, name_normalized="kebab",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000701", name="TRN Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="TRN-0001",
        status="confirmed", subtotal=Decimal("20.00"), total=Decimal("20.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
        price_aed=Decimal("20.00"), qty=1,
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/orders/{order.id}/tax-invoice", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["trn"] == "100987654300003"
