"""Category 6 — CRM / loyalty full wiring tests."""

from datetime import date
from decimal import Decimal

import pytest


async def _customer(db_session, restaurant, phone="+971500008801"):
    from app.ordering.models import Customer

    c = Customer(
        restaurant_id=restaurant.id,
        phone=phone,
        name="CRM Test",
        total_orders=4,
        total_spend=Decimal("400.00"),
    )
    db_session.add(c)
    await db_session.flush()
    return c


@pytest.mark.anyio
async def test_phone_history_notes_vip_birthday(db_session, restaurant):
    from app.ordering.service import patch_customer

    c = await _customer(db_session, restaurant)
    updated = await patch_customer(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=c.id,
        name="VIP Guest",
        phone="+971500008802",
        marketing_opted_in=None,
        notes="Prefers window seat",
        allergy_notes="peanuts",
        birthday=date(1990, 7, 9),
        anniversary=date(2015, 6, 1),
        is_vip=True,
    )
    assert updated.phone == "+971500008802"
    assert updated.notes == "Prefers window seat"
    assert updated.allergy_notes == "peanuts"
    assert updated.is_vip is True
    assert updated.birthday == date(1990, 7, 9)

    from app.loyalty.crm import list_phone_history

    hist = await list_phone_history(
        db_session, restaurant_id=restaurant.id, customer_id=c.id
    )
    assert any(h.phone == "+971500008801" for h in hist)


@pytest.mark.anyio
async def test_stamps_points_favorites_aov(db_session, restaurant):
    from app.loyalty.crm import (
        add_stamp,
        award_loyalty_points,
        compute_aov_clv,
        high_value_customers,
        redeem_stamp_reward,
        refresh_favorites,
    )
    from app.menu.models import Dish, Menu
    from app.ordering.models import Order, OrderItem

    c = await _customer(db_session, restaurant, phone="+971500008810")
    metrics = compute_aov_clv(c)
    assert metrics["average_order_value_aed"] == Decimal("100.00")
    assert metrics["customer_lifetime_value_aed"] == Decimal("400.00")

    card = await add_stamp(
        db_session, restaurant_id=restaurant.id, customer_id=c.id, stamps_required=3, count=3
    )
    assert card.stamps == 3
    card2, coupon = await redeem_stamp_reward(
        db_session, restaurant_id=restaurant.id, customer_id=c.id
    )
    assert card2.stamps == 0
    assert card2.rewards_redeemed == 1
    assert coupon is not None

    bal = await award_loyalty_points(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=c.id,
        points=25,
        reason="test",
        idempotency_key="pts-test-1",
    )
    assert bal == 25

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Shawarma",
        price_aed=Decimal("20"),
        is_available=True,
        name_normalized="shawarma",
    )
    db_session.add(dish)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=c.id,
        order_number="CRM-1",
        status="delivered",
        subtotal=Decimal("20"),
        total=Decimal("20"),
    )
    db_session.add(order)
    await db_session.flush()
    db_session.add(
        OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=1,
            dish_name="Shawarma",
            price_aed=Decimal("20"),
            qty=2,
        )
    )
    await db_session.flush()
    favs = await refresh_favorites(
        db_session, restaurant_id=restaurant.id, customer_id=c.id
    )
    assert any(f.dish_name == "Shawarma" and f.order_count == 2 for f in favs)

    hv = await high_value_customers(
        db_session, restaurant_id=restaurant.id, min_spend_aed=Decimal("100"), min_orders=1
    )
    assert any(x.id == c.id for x in hv)


@pytest.mark.anyio
async def test_nps_detractor_opens_ticket(db_session, restaurant):
    from app.loyalty.nps import record_nps_response
    from app.ordering.models import Order
    from app.tickets.models import Ticket

    c = await _customer(db_session, restaurant, phone="+971500008820")
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=c.id,
        order_number="NPS-1",
        status="delivered",
        subtotal=Decimal("30"),
        total=Decimal("30"),
    )
    db_session.add(order)
    await db_session.flush()
    await record_nps_response(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=c.id,
        order_id=order.id,
        score=3,
        comment="cold food",
    )
    ticket = await db_session.scalar(
        __import__("sqlalchemy", fromlist=["select"]).select(Ticket).where(
            Ticket.order_id == order.id
        )
    )
    assert ticket is not None
    assert ticket.status == "open"


@pytest.mark.anyio
async def test_category6_http_profile_and_high_value(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    c = Customer(
        restaurant_id=restaurant.id,
        phone="+971500008830",
        name="HTTP CRM",
        total_orders=5,
        total_spend=Decimal("500"),
        is_vip=True,
        birthday=date.today(),
        notes="VIP regular",
    )
    db_session.add(c)
    await db_session.flush()

    prof = await client.get(
        f"/api/v1/ordering/customers/{c.id}", headers=auth_headers
    )
    assert prof.status_code == 200, prof.text
    body = prof.json()
    assert body["is_vip"] is True
    assert body["notes"] == "VIP regular"
    assert body["average_order_value_aed"] is not None
    assert body["customer_lifetime_value_aed"] is not None
    assert "stamp_card" in body

    patch = await client.patch(
        f"/api/v1/ordering/customers/{c.id}",
        headers=auth_headers,
        json={
            "allergy_notes": "gluten",
            "birthday": "1991-01-15",
            "is_vip": True,
        },
    )
    assert patch.status_code == 200, patch.text
    assert patch.json()["allergy_notes"] == "gluten"

    hv = await client.get(
        "/api/v1/ordering/customers/high-value?min_spend_aed=100&min_orders=1",
        headers=auth_headers,
    )
    assert hv.status_code == 200, hv.text
    assert any(i["id"] == c.id for i in hv.json()["items"])

    # reorder when no order -> 404
    reo = await client.post(
        f"/api/v1/ordering/customers/{c.id}/reorder-last",
        headers=auth_headers,
    )
    assert reo.status_code == 404
