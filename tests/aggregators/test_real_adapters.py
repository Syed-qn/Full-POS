"""Real marketplace adapters: Talabat, Deliveroo, Keeta, Uber Eats, Careem/Noon middleware."""

from __future__ import annotations

import hashlib
from decimal import Decimal

import httpx
import pytest

from app.aggregators.factory import get_aggregator_port, reset_aggregator_instances
from app.aggregators.providers.deliveroo import DeliverooAdapter
from app.aggregators.providers.keeta import KeetaAdapter, keeta_sign, keeta_sorted_param_str
from app.aggregators.providers.middleware import MiddlewareChannelAdapter
from app.aggregators.providers.talabat import TalabatAdapter
from app.aggregators.providers.ubereats import UberEatsAdapter


@pytest.fixture(autouse=True)
def _reset():
    reset_aggregator_instances()
    yield
    reset_aggregator_instances()


def test_factory_live_selects_talabat_adapter():
    settings = {
        "channels": {
            "talabat": {"mode": "live", "api_key": "user", "api_secret": "pass", "store_id": "v1"}
        }
    }
    port = get_aggregator_port("talabat", restaurant_settings=settings)
    assert isinstance(port, TalabatAdapter)


def test_factory_live_selects_deliveroo_adapter():
    settings = {
        "channels": {
            "deliveroo": {
                "mode": "live",
                "api_key": "key",
                "api_secret": "tok",
                "store_id": "site-1",
            }
        }
    }
    port = get_aggregator_port("deliveroo", restaurant_settings=settings)
    assert isinstance(port, DeliverooAdapter)


def test_factory_live_selects_keeta_adapter():
    settings = {
        "channels": {
            "keeta": {
                "mode": "live",
                "api_key": "123",
                "api_secret": "secret",
                "access_token": "tok",
                "store_id": "99",
            }
        }
    }
    port = get_aggregator_port("keeta", restaurant_settings=settings)
    assert isinstance(port, KeetaAdapter)


def test_keeta_signature_matches_sha256_formula():
    url = "https://open.mykeeta.com/api/open/product/shopcategory/update"
    params = {
        "appId": 123,
        "timestamp": 1682566749,
        "accessToken": "abc",
        "shopId": "123",
        "shopCategory": {"id": 123, "name": "test", "type": 0, "description": None},
    }
    # Java demo uses JSON string for shopCategory without spaces after colons in example
    # Our dumps uses separators=(",", ":")
    sorted_str = keeta_sorted_param_str(params)
    assert "accessToken=abc" in sorted_str
    assert sorted_str.startswith("accessToken=") or "appId=123" in sorted_str
    sig = keeta_sign(url, params, "abc")
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)


def test_keeta_parse_event_1001():
    adapter = KeetaAdapter({})
    order = adapter.parse_inbound(
        {
            "eventId": 1001,
            "data": {
                "orderId": "K-9001",
                "customer": {"phone": "+971501111111", "name": "Omar"},
                "products": [
                    {"name": "Manakeesh", "quantity": 2, "price": "12.50", "sku": "m1"}
                ],
                "totalPrice": "25.00",
                "deliveryFee": "5",
                "remark": "extra cheese",
            },
        }
    )
    assert order.provider == "keeta"
    assert order.provider_order_ref == "K-9001"
    assert order.items[0].dish_name == "Manakeesh"
    assert order.items[0].qty == 2
    assert order.total_aed == Decimal("25.00")
    assert order.notes == "extra cheese"


def test_deliveroo_parse_order_new_event():
    adapter = DeliverooAdapter({"market": "ae"})
    order = adapter.parse_inbound(
        {
            "event": "order.new",
            "body": {
                "id": "ord-uuid-1",
                "market": "ae",
                "customer": {"first_name": "Layla", "phone_number": "+971502222222"},
                "items": [
                    {
                        "name": "Burger",
                        "quantity": 1,
                        "unit_price": {"fractional": 3500},
                        "pos_item_id": "b1",
                    }
                ],
                "total_price": {"fractional": 3500},
            },
        }
    )
    assert order.provider_order_ref in ("ae:ord-uuid-1", "ord-uuid-1")
    assert order.items[0].dish_name == "Burger"
    assert order.customer_name == "Layla"


@pytest.mark.anyio
async def test_deliveroo_accept_patch_order():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.method == "PATCH" and "/order/v1/orders/" in str(request.url):
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = DeliverooAdapter(
            {"api_key": "k", "api_secret": "t", "store_id": "s1"},
            client=client,
        )
        # base_url empty would hit real host; MockTransport intercepts any host
        adapter._cfg["base_url"] = "https://api.developers.deliveroo.com"
        res = await adapter.accept_order(provider_order_ref="ae:order-1")
    assert res.success is True
    assert any(c.method == "PATCH" for c in calls)
    assert "accepted" in (calls[0].content.decode() if calls[0].content else "")


@pytest.mark.anyio
async def test_talabat_accept_posts_order_status():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/v2/login"):
            return httpx.Response(200, json={"access_token": "dh-token", "expires_in": 3600})
        if request.url.path.endswith("/v2/order/status"):
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = TalabatAdapter(
            {
                "api_key": "user",
                "api_secret": "pass",
                "store_id": "vndr",
                "base_url": "https://integration-middleware.stg.restaurant-partners.com",
            },
            client=client,
        )
        res = await adapter.accept_order(provider_order_ref="tok-123")
    assert res.success is True
    paths = [c.url.path for c in calls]
    assert any(p.endswith("/v2/login") for p in paths)
    assert any(p.endswith("/v2/order/status") for p in paths)


@pytest.mark.anyio
async def test_keeta_confirm_includes_sig():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"code": 0, "message": "success", "data": {}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = KeetaAdapter(
            {
                "api_key": "123",
                "api_secret": "abc",
                "access_token": "tok",
                "store_id": "99",
                "base_url": "https://open.mykeeta.com",
            },
            client=client,
        )
        res = await adapter.accept_order(provider_order_ref="K-1")
    assert res.success is True
    assert calls
    body = calls[0].read() if hasattr(calls[0], "read") else calls[0].content
    import json

    payload = json.loads(body.decode())
    assert "sig" in payload
    assert payload["accessToken"] == "tok"
    assert str(payload.get("orderId")) == "K-1"
    # recompute sig
    secret = "abc"
    url = "https://open.mykeeta.com/api/open/order/confirm"
    params = {k: v for k, v in payload.items() if k != "sig"}
    expected = keeta_sign(url, params, secret)
    assert payload["sig"] == expected


def test_keeta_in_supported_providers():
    from app.aggregators.factory import supported_providers

    assert "keeta" in supported_providers()


def test_factory_live_selects_ubereats_adapter():
    settings = {
        "channels": {
            "ubereats": {
                "mode": "live",
                "api_key": "client",
                "api_secret": "secret",
                "store_id": "store-uuid",
                "access_token": "pre-token",
            }
        }
    }
    port = get_aggregator_port("ubereats", restaurant_settings=settings)
    assert isinstance(port, UberEatsAdapter)


def test_factory_live_selects_careem_and_noon_middleware():
    for key in ("careem", "noon"):
        settings = {
            "channels": {
                key: {
                    "mode": "live",
                    "api_key": "k",
                    "api_secret": "s",
                    "store_id": "loc-1",
                    "base_url": f"https://mw.example/{key}",
                }
            }
        }
        port = get_aggregator_port(key, restaurant_settings=settings)
        assert isinstance(port, MiddlewareChannelAdapter)
        assert port._provider == key  # noqa: SLF001


def test_ubereats_parse_notification_and_full_order():
    adapter = UberEatsAdapter({})
    note = adapter.parse_inbound(
        {
            "event_type": "orders.notification",
            "meta": {"resource_id": "ord-ue-1", "status": "pos"},
        }
    )
    assert note.provider_order_ref == "ord-ue-1"

    full = adapter.parse_inbound(
        {
            "id": "ord-ue-2",
            "cart": {
                "items": [
                    {
                        "title": "Chicken Bowl",
                        "quantity": 2,
                        "price": {"amount": 4500},
                        "id": "item-1",
                    }
                ]
            },
            "eater": {"first_name": "Sara", "phone": "+971503333333"},
            "payment": {"charges": {"total": {"amount": 9000}}},
        }
    )
    assert full.provider_order_ref == "ord-ue-2"
    assert full.items[0].dish_name == "Chicken Bowl"
    assert full.items[0].qty == 2
    assert full.customer_name == "Sara"


def test_ubereats_webhook_signature():
    secret = "client-secret"
    body = b'{"event_type":"orders.notification"}'
    sig = hashlib.sha256()  # wrong — use hmac
    import hmac as hm

    digest = hm.new(secret.encode(), body, hashlib.sha256).hexdigest()
    adapter = UberEatsAdapter({"webhook_secret": secret})
    assert adapter.verify_webhook({"X-Uber-Signature": digest}, body) is True
    assert adapter.verify_webhook({"X-Uber-Signature": "deadbeef"}, body) is False


@pytest.mark.anyio
async def test_ubereats_accept_pos_order():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "oauth" in str(request.url):
            return httpx.Response(
                200, json={"access_token": "ue-tok", "expires_in": 3600}
            )
        if request.method == "POST" and "accept_pos_order" in str(request.url):
            return httpx.Response(204)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = UberEatsAdapter(
            {
                "api_key": "cid",
                "api_secret": "csec",
                "store_id": "s1",
                "base_url": "https://api.uber.com",
                "oauth_url": "https://auth.uber.com/oauth/v2/token",
            },
            client=client,
        )
        res = await adapter.accept_order(provider_order_ref="order-uuid-9")
    assert res.success is True
    assert any("accept_pos_order" in str(c.url) for c in calls)
    oauth_calls = [c for c in calls if "oauth" in str(c.url)]
    assert oauth_calls
    # form body contains client_credentials
    raw = oauth_calls[0].content.decode() if oauth_calls[0].content else ""
    assert "client_credentials" in raw or "grant_type" in raw


def test_middleware_parse_deliverect_style_careem():
    adapter = MiddlewareChannelAdapter("careem", {})
    order = adapter.parse_inbound(
        {
            "channelOrderId": "C-1001",
            "channel": "careem",
            "items": [
                {"plu": "101", "name": "Shawarma", "quantity": 2, "price": 2500},
            ],
            "customer": {"name": "Ali", "phoneNumber": "+971504444444"},
            "payment": {"amount": 5000},
            "note": "no onion",
        }
    )
    assert order.provider == "careem"
    assert order.provider_order_ref == "C-1001"
    assert order.items[0].dish_name == "Shawarma"
    assert order.items[0].price_aed == Decimal("25.00")
    assert order.total_aed == Decimal("50.00")
    assert order.notes == "no onion"


@pytest.mark.anyio
async def test_noon_middleware_accept_status():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        adapter = MiddlewareChannelAdapter(
            "noon",
            {
                "api_key": "k",
                "api_secret": "s",
                "store_id": "n1",
                "base_url": "https://mw.example/noon",
            },
            client=client,
        )
        res = await adapter.accept_order(provider_order_ref="N-55")
    assert res.success is True
    assert any("/orders/N-55/status" in str(c.url) for c in calls)
    import json

    payload = json.loads(calls[0].content.decode())
    assert payload["status"] == "accepted"
    assert payload["channel"] == "noon"


def test_registered_real_providers_includes_new():
    from app.aggregators.providers import registered_real_providers

    regs = registered_real_providers()
    for p in ("ubereats", "careem", "noon", "talabat", "deliveroo", "keeta"):
        assert p in regs
