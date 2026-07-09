"""Category 8 — aggregator + multi-channel integrations full wiring tests."""

from datetime import date
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_supported_providers_include_noon_zomato():
    from app.aggregators.factory import supported_providers

    providers = supported_providers()
    for p in ("talabat", "deliveroo", "careem", "ubereats", "noon", "zomato"):
        assert p in providers


@pytest.mark.anyio
async def test_ingest_idempotent_and_source_channel(db_session, restaurant):
    from app.aggregators.mock import MockAggregator
    from app.aggregators.service import ingest_inbound_order

    # Enable + accept talabat
    restaurant.settings = {
        **(restaurant.settings or {}),
        "channels": {"talabat": {"enabled": True, "accepting": True, "commission_pct": 25}},
    }
    payload = {
        "order_id": "TB-IDEM-1",
        "customer": {"phone": "+971500008001", "name": "Guest"},
        "items": [{"name": "Shawarma", "quantity": 1, "price": "20.00"}],
        "total": "20.00",
    }
    gw = MockAggregator("talabat")
    o1 = await ingest_inbound_order(
        db_session,
        restaurant_id=restaurant.id,
        provider="talabat",
        payload=payload,
        gateway=gw,
        restaurant=restaurant,
    )
    await db_session.commit()
    o2 = await ingest_inbound_order(
        db_session,
        restaurant_id=restaurant.id,
        provider="talabat",
        payload=payload,
        gateway=gw,
        restaurant=restaurant,
    )
    await db_session.commit()
    assert o1.id == o2.id
    assert o1.source_channel == "talabat"
    assert o1.aggregator_source == "talabat"


@pytest.mark.anyio
async def test_ingest_paused_channel_raises(db_session, restaurant):
    from app.aggregators.mock import MockAggregator
    from app.aggregators.service import ChannelPausedError, ingest_inbound_order

    restaurant.settings = {
        **(restaurant.settings or {}),
        "channels": {"deliveroo": {"enabled": True, "accepting": False}},
    }
    gw = MockAggregator("deliveroo")
    with pytest.raises(ChannelPausedError):
        await ingest_inbound_order(
            db_session,
            restaurant_id=restaurant.id,
            provider="deliveroo",
            payload={
                "order_id": "DL-PAUSE",
                "customer": {"phone": "+971500008002", "name": "X"},
                "items": [{"name": "Pizza", "quantity": 1, "price": "30"}],
                "total": "30",
            },
            gateway=gw,
            restaurant=restaurant,
        )


@pytest.mark.anyio
async def test_menu_stock_sync_and_pause(db_session, restaurant):
    from app.aggregators.factory import get_aggregator_port, reset_aggregator_instances
    from app.aggregators.service import (
        set_channel_accepting,
        sync_menu_to_providers,
        sync_stock_to_providers,
    )
    from app.menu.models import Dish, Menu

    reset_aggregator_instances()
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Test Dish",
        price_aed=Decimal("15.00"),
        is_available=True,
        name_normalized="test dish",
        stock_remaining=0,
    )
    db_session.add(dish)
    await db_session.flush()

    results = await sync_menu_to_providers(
        db_session, restaurant=restaurant, providers=["talabat"]
    )
    assert results and results[0]["success"]
    gw = get_aggregator_port("talabat")
    assert len(gw.last_menu_push) >= 1

    stock = await sync_stock_to_providers(
        db_session, restaurant=restaurant, providers=["talabat"]
    )
    assert stock[0]["items_touched"] >= 1

    cfg = await set_channel_accepting(
        db_session, restaurant=restaurant, channel="talabat", accepting=False
    )
    assert cfg["talabat"]["accepting"] is False
    assert gw.last_store_status is False
    await db_session.commit()


@pytest.mark.anyio
async def test_commission_and_profit_reports(db_session, restaurant):
    from app.aggregators.mock import MockAggregator
    from app.aggregators.service import (
        channel_commission_report,
        channel_profit_report,
        ingest_inbound_order,
        reconciliation,
    )

    restaurant.settings = {
        **(restaurant.settings or {}),
        "channels": {
            "talabat": {"enabled": True, "accepting": True, "commission_pct": 25},
        },
    }
    gw = MockAggregator("talabat")
    await ingest_inbound_order(
        db_session,
        restaurant_id=restaurant.id,
        provider="talabat",
        payload={
            "order_id": "TB-COMM-1",
            "customer": {"phone": "+971500008003", "name": "A"},
            "items": [{"name": "Item", "quantity": 1, "price": "100.00"}],
            "total": "100.00",
        },
        gateway=gw,
        restaurant=restaurant,
    )
    await db_session.commit()

    today = date.today()
    recon = await reconciliation(
        db_session,
        restaurant_id=restaurant.id,
        start_date=today,
        end_date=today,
        restaurant_settings=restaurant.settings,
    )
    assert recon["talabat"]["order_count"] == 1
    assert recon["talabat"]["commission_aed"] == Decimal("25.00")
    assert recon["talabat"]["net_aed"] == Decimal("75.00")

    rows = await channel_commission_report(
        db_session,
        restaurant_id=restaurant.id,
        start_date=today,
        end_date=today,
        restaurant_settings=restaurant.settings,
    )
    tal = next(r for r in rows if r["channel"] == "talabat")
    assert tal["commission_aed"] == Decimal("25.00")

    profit = await channel_profit_report(
        db_session,
        restaurant_id=restaurant.id,
        start_date=today,
        end_date=today,
        restaurant_settings=restaurant.settings,
        food_cost_pct=30.0,
    )
    ptal = next(r for r in profit if r["channel"] == "talabat")
    # net 75 - food 30 = 45
    assert ptal["estimated_profit_aed"] == Decimal("45.00")


@pytest.mark.anyio
async def test_public_storefront_order(db_session, restaurant):
    from app.aggregators.service import (
        ensure_public_slug,
        get_restaurant_by_slug,
        place_public_channel_order,
        public_menu_for_restaurant,
    )
    from app.menu.models import Dish, Menu

    slug = await ensure_public_slug(db_session, restaurant=restaurant, preferred="c8-test-cafe")
    await db_session.commit()
    assert slug
    rest = await get_restaurant_by_slug(db_session, slug=slug)
    assert rest is not None
    assert rest.id == restaurant.id

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=9,
        name="Kiosk Wrap",
        price_aed=Decimal("18.00"),
        is_available=True,
        name_normalized="kiosk wrap",
    )
    db_session.add(dish)
    await db_session.flush()

    items = await public_menu_for_restaurant(
        db_session, restaurant_id=restaurant.id, channel="website"
    )
    assert any(i["name"] == "Kiosk Wrap" for i in items)

    order = await place_public_channel_order(
        db_session,
        restaurant=restaurant,
        channel="website",
        customer_phone="+971500008099",
        customer_name="Web Guest",
        items=[{"dish_id": dish.id, "qty": 2}],
    )
    await db_session.commit()
    assert order.source_channel == "website"
    assert order.total == Decimal("36.00")


@pytest.mark.anyio
async def test_settlement_and_api_channels(client, auth_headers, restaurant):
    # Enable talabat via API
    r = await client.put(
        "/api/v1/aggregators/channels",
        json={
            "channels": {
                "talabat": {
                    "enabled": True,
                    "accepting": True,
                    "commission_pct": 25,
                }
            }
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["channels"]["talabat"]["enabled"] is True

    slug_r = await client.post(
        "/api/v1/aggregators/public-slug",
        json={"slug": "api-c8-shop"},
        headers=auth_headers,
    )
    assert slug_r.status_code == 200
    assert slug_r.json()["public_slug"]

    key_resp = await client.post(
        "/api/v1/api-keys",
        json={"label": "Cat8 Key"},
        headers=auth_headers,
    )
    api_key = key_resp.json()["api_key"]
    wh = await client.post(
        "/api/v1/aggregators/talabat/webhook",
        json={
            "order_id": "TB-API-9",
            "customer": {"phone": "+971500008010", "name": "API"},
            "items": [{"name": "Falafel", "quantity": 1, "price": "12.00"}],
            "total": "12.00",
        },
        headers={"X-API-Key": api_key},
    )
    assert wh.status_code == 201
    assert wh.json()["source_channel"] == "talabat"

    today = date.today().isoformat()
    recon = await client.get(
        f"/api/v1/aggregators/reconciliation?start_date={today}&end_date={today}",
        headers=auth_headers,
    )
    assert recon.status_code == 200
    assert recon.json()["talabat"]["order_count"] >= 1

    comm = await client.get(
        f"/api/v1/aggregators/reports/commission?start_date={today}&end_date={today}",
        headers=auth_headers,
    )
    assert comm.status_code == 200
    assert "rows" in comm.json()

    sett = await client.post(
        "/api/v1/aggregators/settlements",
        json={
            "provider": "talabat",
            "period_start": today,
            "period_end": today,
            "order_count": 1,
            "gross_revenue_aed": "12.00",
            "commission_aed": "3.00",
        },
        headers=auth_headers,
    )
    assert sett.status_code == 201
    assert sett.json()["net_aed"] == "9.00"

    inbox = await client.get(
        "/api/v1/aggregators/inbox?channel=talabat",
        headers=auth_headers,
    )
    assert inbox.status_code == 200
    assert len(inbox.json()["orders"]) >= 1

    pause = await client.post(
        "/api/v1/aggregators/channels/talabat/pause",
        headers=auth_headers,
    )
    assert pause.status_code == 200
    assert pause.json()["channels"]["talabat"]["accepting"] is False


@pytest.mark.anyio
async def test_noon_zomato_webhooks(client, auth_headers):
    key_resp = await client.post(
        "/api/v1/api-keys",
        json={"label": "Noon Zomato"},
        headers=auth_headers,
    )
    api_key = key_resp.json()["api_key"]

    # Enable channels first
    await client.put(
        "/api/v1/aggregators/channels",
        json={
            "channels": {
                "noon": {"enabled": True, "accepting": True},
                "zomato": {"enabled": True, "accepting": True},
            }
        },
        headers=auth_headers,
    )

    for provider, oid in (("noon", "NN-1"), ("zomato", "ZM-1")):
        resp = await client.post(
            f"/api/v1/aggregators/{provider}/webhook",
            json={
                "order_id": oid,
                "customer": {"phone": f"+9715000080{provider[:2]}", "name": provider},
                "items": [{"name": "Meal", "quantity": 1, "price": "40.00"}],
                "total": "40.00",
            },
            headers={"X-API-Key": api_key},
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["aggregator_source"] == provider


@pytest.mark.anyio
async def test_orders_list_channel_filter(client, auth_headers):
    key_resp = await client.post(
        "/api/v1/api-keys", json={"label": "Filter Key"}, headers=auth_headers
    )
    api_key = key_resp.json()["api_key"]
    await client.put(
        "/api/v1/aggregators/channels",
        json={"channels": {"careem": {"enabled": True, "accepting": True}}},
        headers=auth_headers,
    )
    await client.post(
        "/api/v1/aggregators/careem/webhook",
        json={
            "order_id": "CR-FILT",
            "customer": {"phone": "+971500008077", "name": "C"},
            "items": [{"name": "Burger", "quantity": 1, "price": "25.00"}],
            "total": "25.00",
        },
        headers={"X-API-Key": api_key},
    )
    resp = await client.get("/api/v1/orders?channel=careem", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 1
    assert all(
        (o.get("source_channel") == "careem" or o.get("aggregator_source") == "careem")
        for o in body
    )
