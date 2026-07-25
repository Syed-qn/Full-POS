"""Firing a new KOT round on a dine-in tab clears a stale bill request, so the
cashier floor shows the table as Occupied, not stuck on BILL."""

from decimal import Decimal

import pytest


async def _restaurant(db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


@pytest.mark.anyio
async def test_kot_round_clears_needs_bill(client, auth_headers, db_session):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem
    from app.tables.models import DiningTable

    restaurant = await _restaurant(db_session)
    table = DiningTable(
        restaurant_id=restaurant.id, label="B9", seats=4, status="needs_bill",
        pos_x=1.0, pos_y=1.0,
    )
    db_session.add(table)
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Kebab",
        price_aed=Decimal("20.00"), category="Grills", is_available=True,
        name_normalized="kebab",
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000777", name="T")
    db_session.add_all([dish, cust])
    await db_session.flush()
    # An open, already-fired dine-in tab on a table that asked for the bill.
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="KB-0001",
        status="preparing", subtotal=Decimal("20.00"), total=Decimal("20.00"),
        order_type="dine_in", table_id=table.id,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id, dish_id=dish.id, dish_number=1, dish_name="Kebab",
            price_aed=Decimal("20.00"), qty=1, kitchen_status="ready",
        )
    )
    await db_session.commit()

    # Cashier adds another round and it fires to the kitchen.
    resp = await client.post(
        f"/api/v1/orders/{order.id}/items",
        json={"items": [{"dish_id": dish.id, "qty": 1}]},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    await db_session.refresh(table)
    assert table.status == "ordered"  # no longer stuck on needs_bill
