"""Transmit takes the order number off the bill, not the internal row id.

The form asked for "Order ID" and posted `order_id`, which is the database
primary key. Nobody standing in a restaurant knows that number; the receipt says
R1-0007. The id still works for API callers that hold one.
"""

from decimal import Decimal

import pytest
from sqlalchemy import select


async def _seed_order(db_session, *, order_number: str):
    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order, OrderItem

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    restaurant.settings = {
        **(restaurant.settings or {}),
        "trn": "100123456700003",
        "legal_name": "Biryani House LLC",
        "e_invoice_enabled": True,
        "asp_provider": "mock",
    }
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=3,
        name="Rice",
        price_aed=Decimal("20.00"),
        is_available=True,
        name_normalized="rice",
    )
    db_session.add(dish)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009931", name="ON")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number=order_number,
        status="confirmed",
        subtotal=Decimal("20.00"),
        total=Decimal("21.00"),
        vat_rate=Decimal("0.05"),
        vat_amount_aed=Decimal("1.00"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=3,
            dish_name="Rice",
            price_aed=Decimal("20.00"),
            qty=1,
        )
    )
    await db_session.commit()
    return order.id


@pytest.mark.anyio
async def test_transmit_by_order_number(client, auth_headers, db_session, seed_biryani_menu):
    order_id = await _seed_order(db_session, order_number="R1-0007")

    resp = await client.post(
        "/api/v1/compliance/e-invoice/transmit",
        headers=auth_headers,
        json={"order_number": "R1-0007"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["order_id"] == order_id
    assert resp.json()["status"] == "accepted"


@pytest.mark.anyio
async def test_a_leading_hash_is_tolerated(client, auth_headers, db_session, seed_biryani_menu):
    order_id = await _seed_order(db_session, order_number="R1-0008")

    resp = await client.post(
        "/api/v1/compliance/e-invoice/transmit",
        headers=auth_headers,
        json={"order_number": "  #R1-0008 "},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["order_id"] == order_id


@pytest.mark.anyio
async def test_unknown_number_says_so_by_number(
    client, auth_headers, db_session, seed_biryani_menu
):
    await _seed_order(db_session, order_number="R1-0009")

    resp = await client.post(
        "/api/v1/compliance/e-invoice/transmit",
        headers=auth_headers,
        json={"order_number": "R1-9999"},
    )
    assert resp.status_code == 404, resp.text
    assert "R1-9999" in resp.json()["detail"]


@pytest.mark.anyio
async def test_neither_identifier_is_rejected(client, auth_headers):
    resp = await client.post(
        "/api/v1/compliance/e-invoice/transmit",
        headers=auth_headers,
        json={"buyer_trn": "100123456700003"},
    )
    assert resp.status_code == 422, resp.text
