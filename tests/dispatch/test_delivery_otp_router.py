from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed_order(db_session, *, status="arriving", otp="4242"):
    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    rider = Rider(
        restaurant_id=restaurant.id,
        name="Router Rider OTP",
        phone="+971500000098",
        status="on_delivery",
    )
    db_session.add(rider)
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009997", name="OTP Cust")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="OTP-0001",
        status=status, rider_id=rider.id, delivery_otp=otp,
        subtotal=Decimal("10.00"), total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.commit()
    return restaurant, order


@pytest.mark.anyio
async def test_verify_delivery_otp_router_success(client, auth_headers, db_session):
    restaurant, order = await _seed_order(db_session, otp="4242")

    resp = await client.post(
        f"/api/v1/orders/{order.id}/verify-delivery-otp",
        headers=auth_headers,
        json={"otp": "4242"},
    )
    assert resp.status_code == 200
    assert resp.json()["verified"] is True

    await db_session.refresh(order)
    assert order.delivery_otp_verified_at is not None


@pytest.mark.anyio
async def test_verify_delivery_otp_router_wrong_code(client, auth_headers, db_session):
    restaurant, order = await _seed_order(db_session, otp="4242")

    resp = await client.post(
        f"/api/v1/orders/{order.id}/verify-delivery-otp",
        headers=auth_headers,
        json={"otp": "0000"},
    )
    assert resp.status_code == 422

    await db_session.refresh(order)
    assert order.delivery_otp_verified_at is None


@pytest.mark.anyio
async def test_verify_delivery_otp_router_404_unknown_order(client, auth_headers, db_session):
    resp = await client.post(
        "/api/v1/orders/999999/verify-delivery-otp",
        headers=auth_headers,
        json={"otp": "1234"},
    )
    assert resp.status_code == 404
