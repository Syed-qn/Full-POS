"""Category 11 — multi-branch / franchise full wiring tests."""

from datetime import date
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_central_menu_publish_and_branch_price(client):
    signup = await client.post(
        "/api/v1/organizations/signup",
        json={
            "name": "C11 Group",
            "owner_email": "c11@test.ae",
            "password": "hunter2!",
        },
    )
    assert signup.status_code == 201
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    b1 = await client.post(
        "/api/v1/organizations/branches",
        json={
            "name": "Marina",
            "lat": 25.08,
            "lng": 55.14,
            "region": "dubai",
            "currency": "AED",
        },
        headers=headers,
    )
    b2 = await client.post(
        "/api/v1/organizations/branches",
        json={
            "name": "JLT",
            "lat": 25.07,
            "lng": 55.15,
            "region": "dubai",
            "is_central_kitchen": True,
        },
        headers=headers,
    )
    assert b1.status_code == 201 and b2.status_code == 201
    rid1, rid2 = b1.json()["id"], b2.json()["id"]
    assert b2.json()["is_central_kitchen"] is True

    item = await client.post(
        "/api/v1/organizations/menu-items",
        json={
            "name": "C11 Shawarma",
            "base_price_aed": "18.00",
            "category": "Mains",
            "name_ar": "شاورما",
            "dish_number": 101,
        },
        headers=headers,
    )
    assert item.status_code == 201, item.text
    item_id = item.json()["id"]

    price = await client.post(
        "/api/v1/organizations/branch-prices",
        json={
            "org_menu_item_id": item_id,
            "restaurant_id": rid1,
            "price_aed": "20.00",
        },
        headers=headers,
    )
    assert price.status_code == 201

    job = await client.post(
        "/api/v1/organizations/menu-publish",
        json={"target_restaurant_ids": [rid1, rid2]},
        headers=headers,
    )
    assert job.status_code == 201
    job_id = job.json()["id"]
    assert job.json()["status"] == "pending"

    decided = await client.post(
        f"/api/v1/organizations/menu-publish/{job_id}/decide",
        json={"approve": True, "approved_by": "owner"},
        headers=headers,
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "published"
    assert decided.json()["result"]["dishes_touched"] >= 2


@pytest.mark.anyio
async def test_royalty_region_loyalty_promo_member_kitchen(client, db_session):
    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order
    from sqlalchemy import select

    signup = await client.post(
        "/api/v1/organizations/signup",
        json={
            "name": "C11 Roy",
            "owner_email": "c11roy@test.ae",
            "password": "hunter2!",
        },
    )
    headers = {"Authorization": f"Bearer {signup.json()['access_token']}"}

    await client.patch(
        "/api/v1/organizations/me",
        json={"royalty_pct": "10.00", "default_locale": "ar", "settings": {"fx_rates": {"USD": "0.27"}}},
        headers=headers,
    )

    b1 = await client.post(
        "/api/v1/organizations/branches",
        json={"name": "R1", "lat": 25.0, "lng": 55.0, "region": "abu_dhabi"},
        headers=headers,
    )
    b2 = await client.post(
        "/api/v1/organizations/branches",
        json={
            "name": "CK",
            "lat": 25.1,
            "lng": 55.1,
            "region": "dubai",
            "is_central_kitchen": True,
        },
        headers=headers,
    )
    rid1 = b1.json()["id"]
    rid_ck = b2.json()["id"]

    # seed a delivered order for royalty
    rest = await db_session.get(Restaurant, rid1)
    cust = Customer(
        restaurant_id=rid1,
        phone="+971500011001",
        name="OrgCust",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()
    db_session.add(
        Order(
            restaurant_id=rid1,
            customer_id=cust.id,
            order_number="C11-ROY-1",
            status="delivered",
            subtotal=Decimal("100"),
            total=Decimal("100"),
        )
    )
    await db_session.commit()

    today = date.today().isoformat()
    roy = await client.get(
        f"/api/v1/organizations/royalty?start_date={today}&end_date={today}",
        headers=headers,
    )
    assert roy.status_code == 200
    assert roy.json()["royalty_pct"] == 10.0
    assert Decimal(roy.json()["total_royalty_aed"]) == Decimal("10.00")

    reg = await client.get(
        f"/api/v1/organizations/region-report?start_date={today}&end_date={today}",
        headers=headers,
    )
    assert reg.status_code == 200
    regions = {r["region"] for r in reg.json()}
    assert "abu_dhabi" in regions

    cust_r = await client.post(
        "/api/v1/organizations/customers",
        json={"phone": "+971500011099", "name": "Shared", "preferred_locale": "ar"},
        headers=headers,
    )
    assert cust_r.status_code == 201
    loy = await client.post(
        "/api/v1/organizations/loyalty/credit",
        json={"phone": "+971500011099", "points": 50, "spend_aed": "75.00"},
        headers=headers,
    )
    assert loy.status_code == 200
    assert loy.json()["loyalty_points"] == 50

    promo = await client.post(
        "/api/v1/organizations/promotions",
        json={
            "code": "C11SAVE",
            "title": "HQ Promo",
            "discount_aed": "15.00",
            "target_restaurant_ids": [rid1],
        },
        headers=headers,
    )
    assert promo.status_code == 201
    push = await client.post(
        f"/api/v1/organizations/promotions/{promo.json()['id']}/push",
        headers=headers,
    )
    assert push.status_code == 200
    assert str(rid1) in push.json()["pushed_coupon_ids"]

    mem = await client.post(
        "/api/v1/organizations/members",
        json={
            "email": "mgr@c11.ae",
            "name": "Branch Mgr",
            "role": "branch_manager",
            "branch_ids": [rid1],
        },
        headers=headers,
    )
    assert mem.status_code == 201
    assert mem.json()["role"] == "branch_manager"

    ck = await client.post(
        "/api/v1/organizations/central-kitchen/requests",
        json={
            "from_restaurant_id": rid1,
            "items": [{"name": "Dough", "qty": 10, "unit": "kg"}],
            "notes": "weekend prep",
        },
        headers=headers,
    )
    assert ck.status_code == 201, ck.text
    assert ck.json()["central_kitchen_id"] == rid_ck
    st = await client.post(
        f"/api/v1/organizations/central-kitchen/requests/{ck.json()['id']}/status",
        json={"status": "in_production"},
        headers=headers,
    )
    assert st.status_code == 200
    assert st.json()["status"] == "in_production"

    bulk = await client.post(
        "/api/v1/organizations/bulk-update",
        json={
            "restaurant_ids": [rid1, rid_ck],
            "action": "set_locale",
            "payload": {"locale": "ar"},
        },
        headers=headers,
    )
    assert bulk.status_code == 200
    assert bulk.json()["touched"] == 2

    branches = await client.get("/api/v1/organizations/branches", headers=headers)
    locales = {b["id"]: b["locale"] for b in branches.json()}
    assert locales[rid1] == "ar"
