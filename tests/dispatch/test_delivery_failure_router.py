from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed_order(db_session, *, status="arriving"):
    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    rider = Rider(
        restaurant_id=restaurant.id,
        name="Router Rider Failure",
        phone="+971500000097",
        status="on_delivery",
    )
    db_session.add(rider)
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009996", name="Fail Cust")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="FAIL-0001",
        status=status, rider_id=rider.id,
        subtotal=Decimal("10.00"), total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.commit()
    return restaurant, order


@pytest.mark.anyio
async def test_delivery_failed_router_sets_reason(client, auth_headers, db_session):
    restaurant, order = await _seed_order(db_session, status="arriving")

    resp = await client.post(
        f"/api/v1/orders/{order.id}/delivery-failed",
        headers=auth_headers,
        json={"reason": "gate locked, no answer"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "undeliverable"

    await db_session.refresh(order)
    assert order.status == "undeliverable"
    assert order.delivery_failure_reason == "gate locked, no answer"


@pytest.mark.anyio
async def test_delivery_failed_router_rejects_bad_status(client, auth_headers, db_session):
    restaurant, order = await _seed_order(db_session, status="preparing")

    resp = await client.post(
        f"/api/v1/orders/{order.id}/delivery-failed",
        headers=auth_headers,
        json={"reason": "too early"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_delivery_failed_router_404_unknown_order(client, auth_headers, db_session):
    resp = await client.post(
        "/api/v1/orders/999999/delivery-failed",
        headers=auth_headers,
        json={"reason": "x"},
    )
    assert resp.status_code == 404
