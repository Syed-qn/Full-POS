from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_tax_invoice_endpoint(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    restaurant.settings = {**restaurant.settings, "trn": "100123456700003"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Shawarma",
        price_aed=Decimal("18.00"), is_available=True, name_normalized="shawarma",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000011", name="Tax Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="TX-0001",
        status="confirmed", subtotal=Decimal("18.00"), total=Decimal("18.00"),
        vat_rate=Decimal("0.0500"), vat_amount_aed=Decimal("0.90"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(OrderItem(
        order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Shawarma",
        price_aed=Decimal("18.00"), qty=1,
    ))
    await db_session.commit()

    resp = await client.get(f"/api/v1/orders/{order.id}/tax-invoice", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["trn"] == "100123456700003"
    assert body["invoice_number"] == "TX-0001"
    assert body["vat_amount_aed"] == "0.90"
