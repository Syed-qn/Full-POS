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


@pytest.mark.anyio
async def test_settling_frees_the_table_row_not_just_the_display(
    client, auth_headers, db_session
):
    """The stale-needs_bill bug at its source.

    settle_on_premise_if_paid used to leave the table row alone, on the grounds
    that "the floor only counts open orders" — and the floor listing does hide an
    order-driven status while nothing is open. But hiding is not clearing: the row
    stayed "needs_bill" for good, and the cashier floor's purple BILL badge came
    back the moment the next tab opened on that table. A cashier opening a table
    nobody had asked a bill for saw BILL instead of Occupied.
    """
    from decimal import Decimal

    from app.ordering.models import Customer, Order
    from app.ordering.service import settle_on_premise_if_paid
    from app.payments.models import PaymentTransaction
    from app.tables.models import DiningTable

    restaurant = await _restaurant(db_session)
    table = DiningTable(
        restaurant_id=restaurant.id, label="B8", seats=2, status="needs_bill",
        pos_x=2.0, pos_y=2.0,
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000778", name="S")
    db_session.add_all([table, cust])
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="KB-0002",
        status="preparing", subtotal=Decimal("20.00"), total=Decimal("20.00"),
        order_type="dine_in", table_id=table.id,
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        PaymentTransaction(
            restaurant_id=restaurant.id, order_id=order.id, tender_type="cash",
            amount_aed=Decimal("20.00"), status="succeeded",
        )
    )
    await db_session.flush()

    await settle_on_premise_if_paid(
        db_session, order_id=order.id, restaurant_id=restaurant.id
    )
    await db_session.flush()
    await db_session.refresh(table)

    # The ROW, not the rendering: this is what the next sitting inherits.
    assert table.status == "available"


@pytest.mark.anyio
async def test_a_new_tab_on_a_stale_bill_table_reads_occupied(
    client, auth_headers, db_session
):
    """The same bug from the cashier's side.

    Opening a tab used to clear the table only when it read "available", so a
    table left on "needs_bill" by an earlier sitting kept the BILL badge on a tab
    that had just been opened. Asserted through the TABLES ENDPOINT, because that
    is what the floor draws from — the badge is rendered off this status.
    """
    from decimal import Decimal

    from app.menu.models import Dish, Menu
    from app.tables.models import DiningTable

    restaurant = await _restaurant(db_session)
    table = DiningTable(
        restaurant_id=restaurant.id, label="B7", seats=2, status="needs_bill",
        pos_x=3.0, pos_y=3.0,
    )
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add_all([table, menu])
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Tikka",
        price_aed=Decimal("18.00"), category="Grills", is_available=True,
        name_normalized="tikka",
    )
    db_session.add(dish)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/orders/pos",
        json={
            "order_type": "dine_in",
            "table_id": table.id,
            "customer_phone": "+971500000779",
            "items": [{"dish_id": dish.id, "qty": 1}],
        },
        headers=auth_headers,
    )
    assert resp.status_code in (200, 201), resp.text

    listing = await client.get("/api/v1/tables", headers=auth_headers)
    row = next(t for t in listing.json() if t["id"] == table.id)
    assert row["status"] == "ordered", "a freshly opened tab must not read needs_bill"
