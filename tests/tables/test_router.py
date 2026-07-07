from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_create_seat_and_list(client, auth_headers):
    resp = await client.post(
        "/api/v1/tables", json={"label": "T5", "seats": 4, "pos_x": 10.0, "pos_y": 20.0},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    table_id = resp.json()["id"]
    assert resp.json()["status"] == "available"

    seat = await client.patch(
        f"/api/v1/tables/{table_id}/status", json={"status": "seated"}, headers=auth_headers,
    )
    assert seat.status_code == 200
    assert seat.json()["status"] == "seated"

    listing = await client.get("/api/v1/tables", headers=auth_headers)
    assert listing.status_code == 200
    assert any(t["id"] == table_id and t["status"] == "seated" for t in listing.json())


@pytest.mark.anyio
async def test_invalid_transition_returns_409(client, auth_headers):
    resp = await client.post(
        "/api/v1/tables", json={"label": "T6"}, headers=auth_headers,
    )
    table_id = resp.json()["id"]
    bad = await client.patch(
        f"/api/v1/tables/{table_id}/status", json={"status": "needs_bill"}, headers=auth_headers,
    )
    assert bad.status_code == 409


@pytest.mark.anyio
async def test_transfer_order_endpoint(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )

    t1 = await client.post("/api/v1/tables", json={"label": "T7"}, headers=auth_headers)
    t2 = await client.post("/api/v1/tables", json={"label": "T8"}, headers=auth_headers)
    t1_id, t2_id = t1.json()["id"], t2.json()["id"]

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000055", name="Dine In 2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="D-0002",
        status="confirmed", subtotal=Decimal("30.00"), total=Decimal("30.00"), table_id=t1_id,
    )
    db_session.add(order)
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/tables/{t2_id}/transfer-order", json={"order_id": order.id}, headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["table_id"] == t2_id


@pytest.mark.anyio
async def test_update_table_position_endpoint(client, auth_headers):
    created = await client.post(
        "/api/v1/tables", json={"label": "T9"}, headers=auth_headers,
    )
    table_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/tables/{table_id}/position",
        json={"pos_x": 42.5, "pos_y": 17.0},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["pos_x"] == 42.5
    assert resp.json()["pos_y"] == 17.0

    listing = await client.get("/api/v1/tables", headers=auth_headers)
    assert any(
        t["id"] == table_id and t["pos_x"] == 42.5 and t["pos_y"] == 17.0
        for t in listing.json()
    )


@pytest.mark.anyio
async def test_update_table_position_missing_table_returns_404(client, auth_headers):
    resp = await client.patch(
        "/api/v1/tables/999999/position",
        json={"pos_x": 1.0, "pos_y": 1.0},
        headers=auth_headers,
    )
    assert resp.status_code == 404
