from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed_order(db_session, *, status="assigned"):
    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    rider = Rider(
        restaurant_id=restaurant.id,
        name="Router Rider",
        phone="+971500000099",
        status="on_delivery",
    )
    db_session.add(rider)
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009998", name="Photo Cust")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="PHOTO-0001",
        status=status, rider_id=rider.id,
        subtotal=Decimal("10.00"), total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.commit()
    return restaurant, order


@pytest.mark.anyio
async def test_delivery_photo_router_sets_url(client, auth_headers, db_session):
    restaurant, order = await _seed_order(db_session, status="assigned")

    resp = await client.post(
        f"/api/v1/orders/{order.id}/delivery-photo",
        headers=auth_headers,
        json={"photo_url": "https://cdn.example/proof.jpg"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == order.id

    await db_session.refresh(order)
    assert order.delivery_photo_url == "https://cdn.example/proof.jpg"


@pytest.mark.anyio
async def test_delivery_photo_router_rejects_delivered_order(client, auth_headers, db_session):
    restaurant, order = await _seed_order(db_session, status="delivered")

    resp = await client.post(
        f"/api/v1/orders/{order.id}/delivery-photo",
        headers=auth_headers,
        json={"photo_url": "https://cdn.example/late.jpg"},
    )
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_delivery_photo_router_404_unknown_order(client, auth_headers, db_session):
    resp = await client.post(
        "/api/v1/orders/999999/delivery-photo",
        headers=auth_headers,
        json={"photo_url": "https://cdn.example/x.jpg"},
    )
    assert resp.status_code == 404
