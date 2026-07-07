from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_credentials_lifecycle(client, auth_headers):
    default = await client.get("/api/v1/payments/credentials", headers=auth_headers)
    assert default.status_code == 200
    assert default.json() == {"provider": "mock", "configured": False}

    put = await client.put(
        "/api/v1/payments/credentials",
        json={"provider": "stripe", "secret_key": "sk_test_router_abc"},
        headers=auth_headers,
    )
    assert put.status_code == 200
    assert put.json() == {"provider": "stripe", "configured": True}

    delete = await client.delete("/api/v1/payments/credentials", headers=auth_headers)
    assert delete.status_code == 204

    after = await client.get("/api/v1/payments/credentials", headers=auth_headers)
    assert after.json() == {"provider": "mock", "configured": False}


@pytest.mark.anyio
async def test_charge_and_refund_via_router(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000601", name="Router Pay")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="RTR-0001",
        status="confirmed", subtotal=Decimal("40.00"), total=Decimal("40.00"),
    )
    db_session.add(order)
    await db_session.commit()

    charge = await client.post(
        "/api/v1/payments/charge",
        json={"order_id": order.id, "tender_type": "card", "amount_aed": "40.00", "tip_aed": "5.00"},
        headers=auth_headers,
    )
    assert charge.status_code == 201
    assert charge.json()["status"] == "succeeded"
    txn_id = charge.json()["id"]

    refund = await client.post(
        f"/api/v1/payments/{txn_id}/refund", json={"amount_aed": "40.00"}, headers=auth_headers,
    )
    assert refund.status_code == 200
    assert refund.json()["status"] == "refunded"
