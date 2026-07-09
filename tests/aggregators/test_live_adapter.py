"""Cat 1 residual — live aggregator HTTP adapter + factory mode selection."""

from __future__ import annotations

import hashlib
import hmac
import json
from decimal import Decimal

import httpx
import pytest

from app.aggregators.factory import (
    get_aggregator_port,
    is_live_mode,
    reset_aggregator_instances,
)
from app.aggregators.live import LiveHttpAggregator, parse_marketplace_payload
from app.aggregators.mock import MockAggregator
from app.aggregators.port import MenuPushItem


@pytest.fixture(autouse=True)
def _reset_ports():
    reset_aggregator_instances()
    yield
    reset_aggregator_instances()


def test_parse_unified_and_talabat_shapes():
    unified = parse_marketplace_payload(
        "talabat",
        {
            "order_id": "T-100",
            "customer": {"phone": "+9715000111", "name": "Ali"},
            "items": [{"name": "Biryani", "quantity": 2, "price": "25.00", "sku": "b1"}],
            "total": "50.00",
            "delivery_fee": "5.00",
        },
    )
    assert unified.provider_order_ref == "T-100"
    assert unified.total_aed == Decimal("50.00")
    assert len(unified.items) == 1
    assert unified.items[0].qty == 2

    products = parse_marketplace_payload(
        "careem",
        {
            "orderId": "C-9",
            "customer": {"mobile": "+9715000222", "name": "Sara"},
            "products": [
                {"product_name": "Shawarma", "qty": 1, "unit_price": "18", "plu": "s1"}
            ],
            "grand_total": "18",
        },
    )
    assert products.provider_order_ref == "C-9"
    assert products.items[0].dish_name == "Shawarma"
    assert products.items[0].price_aed == Decimal("18.00")


def test_factory_selects_mock_by_default():
    port = get_aggregator_port("talabat", restaurant_settings={})
    assert isinstance(port, MockAggregator)


def test_factory_selects_live_when_credentials():
    settings = {
        "channels": {
            "talabat": {
                "mode": "live",
                "api_key": "live-key-123",
                "store_id": "store-1",
                "base_url": "https://example.test/v1",
            }
        }
    }
    assert is_live_mode(settings, "talabat") is True
    port = get_aggregator_port("talabat", restaurant_settings=settings)
    assert isinstance(port, LiveHttpAggregator)
    assert port.base_url == "https://example.test/v1"


@pytest.mark.anyio
async def test_live_http_calls_via_mock_transport():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"ok": True})
        if "/accept" in request.url.path:
            return httpx.Response(200, json={"accepted": True})
        if request.url.path.endswith("/menu"):
            return httpx.Response(201, json={"items": 1})
        if "/status" in request.url.path:
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        live = LiveHttpAggregator(
            "talabat",
            {
                "api_key": "k",
                "store_id": "s1",
                "base_url": "https://partner.test/v1",
            },
            client=client,
        )
        health = await live.health_check()
        assert health.success is True
        accept = await live.accept_order(provider_order_ref="ORD-1")
        assert accept.success is True
        menu = await live.push_menu(
            [
                MenuPushItem(
                    dish_id=1,
                    dish_number=101,
                    name="Kebab",
                    price_aed=Decimal("20.00"),
                    is_available=True,
                )
            ]
        )
        assert menu.success is True
        assert menu.items_touched == 1
        st = await live.push_order_status(
            provider_order_ref="ORD-1", status="preparing"
        )
        assert st.success is True

    assert len(calls) >= 4
    assert any(c.headers.get("Authorization") == "Bearer k" for c in calls)


def test_live_webhook_hmac_verification():
    secret = "whsec"
    body = b'{"order_id":"1"}'
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    live = LiveHttpAggregator("deliveroo", {"webhook_secret": secret, "api_key": "k"})
    assert live.verify_webhook({"x-signature": sig}, body) is True
    assert live.verify_webhook({"x-signature": "bad"}, body) is False
    assert live.verify_webhook({"x-aggregator-secret": secret}, body) is True


@pytest.mark.anyio
async def test_ingest_with_live_port_mocked(client, auth_headers, db_session):
    """End-to-end: set channel live + inject mock transport via factory client."""
    from sqlalchemy import select

    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    restaurant.settings = {
        **(restaurant.settings or {}),
        "channels": {
            "talabat": {
                "enabled": True,
                "accepting": True,
                "mode": "live",
                "api_key": "test-key",
                "store_id": "st-1",
                "base_url": "https://partner.test/v1",
            }
        },
    }
    await db_session.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        from app.aggregators.service import ingest_inbound_order

        gw = get_aggregator_port(
            "talabat",
            restaurant_settings=restaurant.settings,
            client=http_client,
        )
        assert isinstance(gw, LiveHttpAggregator)
        order = await ingest_inbound_order(
            db_session,
            restaurant_id=restaurant.id,
            provider="talabat",
            payload={
                "order_id": "LIVE-INGEST-1",
                "customer": {"phone": "+971500099901", "name": "Live"},
                "items": [{"name": "Rice", "quantity": 1, "price": "15.00"}],
                "total": "15.00",
            },
            gateway=gw,
            restaurant=restaurant,
        )
        await db_session.commit()
        assert order.aggregator_source == "talabat"
        assert order.aggregator_order_ref == "LIVE-INGEST-1"
        assert order.order_type == "aggregator"
        # accept_order was called on live adapter
        assert any(
            c.get("url", "").endswith("/orders/LIVE-INGEST-1/accept")
            for c in gw.last_calls
        )


@pytest.mark.anyio
async def test_live_health_endpoint(client, auth_headers, db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    restaurant.settings = {
        **(restaurant.settings or {}),
        "channels": {"talabat": {"mode": "mock"}},
    }
    await db_session.commit()

    resp = await client.post(
        "/api/v1/aggregators/talabat/live-health", headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["provider"] == "talabat"
    assert resp.json()["mode"] == "mock"
    assert resp.json()["success"] is True


@pytest.mark.anyio
async def test_status_push_on_fsm_transition(db_session, restaurant):
    from app.aggregators.factory import get_aggregator_port, reset_aggregator_instances
    from app.ordering.fsm import OrderStatus, transition
    from app.ordering.models import Customer, Order

    reset_aggregator_instances()
    restaurant.settings = {
        **(restaurant.settings or {}),
        "channels": {"deliveroo": {"mode": "mock"}},
    }
    cust = Customer(restaurant_id=restaurant.id, phone="+971500088801", name="Agg")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="AGG-ST-1",
        status=OrderStatus.CONFIRMED,
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        aggregator_source="deliveroo",
        aggregator_order_ref="DR-55",
        source_channel="deliveroo",
        order_type="aggregator",
    )
    db_session.add(order)
    await db_session.flush()

    await transition(db_session, order, OrderStatus.PREPARING, actor="kitchen")
    await db_session.commit()

    gw = get_aggregator_port("deliveroo", restaurant_settings=restaurant.settings)
    assert isinstance(gw, MockAggregator)
    assert ("DR-55", "preparing") in gw.status_pushes


@pytest.mark.anyio
async def test_channel_config_live_fields_and_health_ui_path(
    client, auth_headers, db_session
):
    patch = await client.put(
        "/api/v1/aggregators/channels",
        headers=auth_headers,
        json={
            "channels": {
                "talabat": {
                    "enabled": True,
                    "mode": "live",
                    "api_key": "secret-key",
                    "store_id": "S1",
                    "base_url": "https://example.partners/v1",
                    "webhook_secret": "wh",
                }
            }
        },
    )
    assert patch.status_code == 200, patch.text
    talabat = patch.json()["channels"]["talabat"]
    assert talabat["mode"] == "live"
    assert talabat["api_key_set"] is True
    assert talabat["api_key"] is None  # never echoed
    assert talabat["store_id"] == "S1"
    assert talabat["base_url"] == "https://example.partners/v1"
    assert talabat["webhook_secret_set"] is True
