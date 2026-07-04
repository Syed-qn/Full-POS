async def test_create_and_list_coupon(client, auth_headers):
    resp = await client.post(
        "/api/v1/coupons",
        headers=auth_headers,
        json={"discount_type": "fixed", "discount_value": "10.00", "kind": "multi_use"},
    )
    assert resp.status_code == 201, resp.text
    code = resp.json()["code"]
    assert resp.json()["status"] == "active"

    listed = await client.get("/api/v1/coupons", headers=auth_headers)
    assert listed.status_code == 200
    assert any(c["code"] == code for c in listed.json())


async def test_list_includes_single_use_campaign_coupon(client, auth_headers):
    """Manager single-use promos must appear in the default list (not only multi_use)."""
    resp = await client.post(
        "/api/v1/coupons",
        headers=auth_headers,
        json={"discount_type": "fixed", "discount_value": "5.00", "kind": "single_use"},
    )
    assert resp.status_code == 201, resp.text
    code = resp.json()["code"]

    listed = await client.get("/api/v1/coupons", headers=auth_headers)
    assert listed.status_code == 200
    assert any(c["code"] == code for c in listed.json())


async def test_pause_coupon(client, auth_headers):
    created = await client.post(
        "/api/v1/coupons",
        headers=auth_headers,
        json={"discount_type": "percent", "discount_value": "15.00"},
    )
    code = created.json()["code"]
    paused = await client.post(f"/api/v1/coupons/{code}/pause", headers=auth_headers)
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"


async def test_create_rejects_bad_discount(client, auth_headers):
    resp = await client.post(
        "/api/v1/coupons",
        headers=auth_headers,
        json={"discount_type": "fixed", "discount_value": "0"},
    )
    assert resp.status_code == 422  # pydantic gt=0


async def test_list_coupons_by_phone(db_session, client, auth_headers):
    from decimal import Decimal
    from sqlalchemy import select
    from app.coupons import service as csvc
    from app.identity.models import Restaurant
    from app.ordering.models import Customer
    r = await db_session.scalar(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    c = Customer(restaurant_id=r.id, phone="+971555999003", name="Gamma")
    db_session.add(c)
    await db_session.flush()
    await csvc.issue_coupon(db_session, restaurant_id=r.id, customer_id=c.id, order_id=None,
                            discount_aed=Decimal("12.00"))
    await db_session.commit()

    resp = await client.get("/api/v1/coupons?phone=999003", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["discount_aed"] == "12.00"

    none = await client.get("/api/v1/coupons?phone=000000", headers=auth_headers)
    assert none.json() == []
