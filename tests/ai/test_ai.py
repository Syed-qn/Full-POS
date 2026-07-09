"""Category 14 — AI features full-stack tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_ai_features_catalog(client, auth_headers):
    resp = await client.get("/api/v1/ai/features", headers=auth_headers)
    assert resp.status_code == 200
    keys = {f["key"] for f in resp.json()["features"]}
    assert "daily_sales" in keys
    assert "call_answering" in keys
    assert "reservations" in keys
    assert len(keys) >= 20


@pytest.mark.anyio
async def test_daily_sales_and_sales_drop(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500014001", name="AI1")
    db_session.add(cust)
    await db_session.flush()
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db_session.add(
        Order(
            restaurant_id=restaurant.id,
            customer_id=cust.id,
            order_number="AI-DS-1",
            status="delivered",
            subtotal=Decimal("100.00"),
            total=Decimal("105.00"),
            vat_amount_aed=Decimal("5.00"),
            created_at=now,
        )
    )
    await db_session.commit()

    ds = await client.post("/api/v1/ai/insights/daily-sales", headers=auth_headers)
    assert ds.status_code == 200, ds.text
    assert ds.json()["kind"] == "daily_sales"
    assert "Sales recap" in ds.json()["summary"] or "order" in ds.json()["summary"].lower()

    drop = await client.post(
        "/api/v1/ai/insights/sales-drop?days=7", headers=auth_headers
    )
    assert drop.status_code == 200
    assert drop.json()["kind"] == "sales_drop"


@pytest.mark.anyio
async def test_staff_slow_food_stock_insights(client, auth_headers):
    for path in (
        "/api/v1/ai/insights/staff?days=7",
        "/api/v1/ai/insights/slow-moving?days=14",
        "/api/v1/ai/insights/food-cost",
        "/api/v1/ai/insights/low-stock",
    ):
        resp = await client.post(path, headers=auth_headers)
        assert resp.status_code == 200, f"{path}: {resp.text}"
        assert resp.json()["kind"]
        assert resp.json()["summary"]


@pytest.mark.anyio
async def test_upsell_combos_bundles(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    d = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=101,
        name="AI Kebab",
        price_aed=Decimal("25.00"),
        is_available=True,
        name_normalized="ai kebab",
    )
    db_session.add(d)
    await db_session.commit()

    up = await client.post(
        "/api/v1/ai/upsell",
        headers=auth_headers,
        json={"dish_ids": [d.id], "limit": 3},
    )
    assert up.status_code == 200
    assert "suggestions" in up.json()

    combos = await client.get("/api/v1/ai/combos", headers=auth_headers)
    assert combos.status_code == 200
    assert "combos" in combos.json()

    bundles = await client.post("/api/v1/ai/bundles", headers=auth_headers)
    assert bundles.status_code == 200
    assert bundles.json()["kind"] == "menu_bundle"


@pytest.mark.anyio
async def test_marketing_ai_endpoints(client, auth_headers):
    reo = await client.post("/api/v1/ai/reorder-prompt", headers=auth_headers)
    assert reo.status_code == 200
    assert "body" in reo.json()

    ab = await client.post(
        "/api/v1/ai/abandoned-copy?cart_summary=2x%20Biryani", headers=auth_headers
    )
    assert ab.status_code == 200
    assert "cart" in ab.json()["body"].lower() or "🛒" in ab.json()["body"]

    seg = await client.post("/api/v1/ai/segments", headers=auth_headers)
    assert seg.status_code == 200
    assert seg.json()["kind"] == "segmentation"

    fest = await client.post(
        "/api/v1/ai/festival",
        headers=auth_headers,
        json={"festival": "Eid", "offer": "20% off family meal"},
    )
    assert fest.status_code == 200
    assert fest.json()["kind"] == "festival_campaign"
    assert "Eid" in fest.json()["summary"] or "festival" in fest.json()["summary"].lower()


@pytest.mark.anyio
async def test_review_reply_and_escalate(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.loyalty.models import NpsResponse
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500014002", name="AI2")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="AI-RV-1",
        status="delivered",
        subtotal=Decimal("30.00"),
        total=Decimal("30.00"),
    )
    db_session.add(order)
    await db_session.flush()
    nps = NpsResponse(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_id=order.id,
        score=3,
        comment="Food was cold and late",
    )
    db_session.add(nps)
    await db_session.commit()

    reply = await client.post(
        "/api/v1/ai/reviews/reply",
        headers=auth_headers,
        json={
            "comment": "Food was cold and late",
            "score": 3,
            "order_id": order.id,
            "customer_id": cust.id,
            "nps_response_id": nps.id,
            "escalate": True,
        },
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["sentiment"] == "negative"
    assert reply.json()["escalated"] is True
    assert reply.json()["suggested_reply"]

    esc = await client.post("/api/v1/ai/reviews/escalate", headers=auth_headers)
    assert esc.status_code == 200
    assert "scanned" in esc.json()


@pytest.mark.anyio
async def test_eta_translate_reservation_call(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer, Order

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500014003", name="AI3")
    db_session.add(cust)
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=202,
        name="Chicken Biryani",
        price_aed=Decimal("40.00"),
        is_available=True,
        name_normalized="chicken biryani",
        description="Spicy rice with chicken",
    )
    db_session.add(dish)
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="AI-ETA-1",
        status="assigned",
        subtotal=Decimal("40.00"),
        total=Decimal("40.00"),
        cook_estimate_minutes=20,
        promised_eta=datetime.now(timezone.utc) + timedelta(minutes=45),
        distance_km=4.2,
    )
    db_session.add(order)
    await db_session.commit()

    eta = await client.get(f"/api/v1/ai/eta/{order.id}", headers=auth_headers)
    assert eta.status_code == 200
    assert "explanation" in eta.json()

    tr = await client.post(
        "/api/v1/ai/translate",
        headers=auth_headers,
        json={"dish_id": dish.id, "target_lang": "ar"},
    )
    assert tr.status_code == 200, tr.text
    assert tr.json()["name"]
    assert tr.json()["target_lang"] == "ar"

    when = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    res = await client.post(
        "/api/v1/ai/reservations",
        headers=auth_headers,
        json={
            "party_size": 4,
            "requested_for": when,
            "guest_name": "Sara",
            "phone": "+971500014099",
            "notes": "window seat",
        },
    )
    assert res.status_code == 201, res.text
    assert res.json()["ai_summary"]
    rid = res.json()["id"]

    listed = await client.get("/api/v1/ai/reservations", headers=auth_headers)
    assert listed.status_code == 200
    assert any(r["id"] == rid for r in listed.json())

    call = await client.post(
        "/api/v1/ai/calls",
        headers=auth_headers,
        json={"caller_phone": "+971500014088"},
    )
    assert call.status_code == 201
    cid = call.json()["id"]
    turn = await client.post(
        f"/api/v1/ai/calls/{cid}/turn",
        headers=auth_headers,
        json={"text": "I want to place an order"},
    )
    assert turn.status_code == 200
    assert turn.json()["outcome"] == "order_intent"
    assert len(turn.json()["transcript"]) >= 3


@pytest.mark.anyio
async def test_list_insights(client, auth_headers):
    await client.post("/api/v1/ai/insights/daily-sales", headers=auth_headers)
    listed = await client.get("/api/v1/ai/insights", headers=auth_headers)
    assert listed.status_code == 200
    assert isinstance(listed.json(), list)
