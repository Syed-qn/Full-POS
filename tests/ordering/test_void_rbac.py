from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_non_manager_staff_cannot_void_order(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000801", name="Void Test")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="VOID-0001",
        status="confirmed", subtotal=Decimal("30.00"), total=Decimal("30.00"),
    )
    db_session.add(order)
    await db_session.commit()

    staff_resp = await client.post(
        "/api/v1/staff", json={"name": "Cashier Nour", "role": "cashier", "pin": "4444"},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "4444"})
    staff_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(f"/api/v1/orders/{order.id}/cancel", headers=staff_headers)
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_manager_role_staff_can_void_order(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000802", name="Void Test 2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="VOID-0002",
        status="confirmed", subtotal=Decimal("30.00"), total=Decimal("30.00"),
    )
    db_session.add(order)
    await db_session.commit()

    staff_resp = await client.post(
        "/api/v1/staff", json={"name": "Manager Fatima", "role": "manager", "pin": "5555"},
        headers=auth_headers,
    )
    staff_id = staff_resp.json()["id"]
    login = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "5555"})
    staff_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.post(f"/api/v1/orders/{order.id}/cancel", headers=staff_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
