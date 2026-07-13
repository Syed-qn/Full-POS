"""Multi-tenant SaaS: each restaurant owns its marketplace credentials."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.aggregators.channels import set_channels_config, tenant_webhook_urls
from app.aggregators.factory import get_aggregator_port, is_live_mode, reset_aggregator_instances
from app.aggregators.providers.talabat import TalabatAdapter
from app.aggregators.service import ensure_public_slug
from app.identity.models import Restaurant


@pytest.fixture(autouse=True)
def _reset():
    reset_aggregator_instances()
    yield
    reset_aggregator_instances()


def test_empty_secret_patch_preserves_previous():
    r = Restaurant(
        name="A",
        phone="+971500000001",
        password_hash="x",
        lat=25.0,
        lng=55.0,
        settings={
            "channels": {
                "talabat": {
                    "mode": "live",
                    "api_key": "keep-me",
                    "api_secret": "secret-keep",
                    "store_id": "S1",
                }
            }
        },
    )
    set_channels_config(r, {"talabat": {"store_id": "S2", "api_secret": ""}})
    cfg = r.settings["channels"]["talabat"]
    assert cfg["api_key"] == "keep-me"
    assert cfg["api_secret"] == "secret-keep"
    assert cfg["store_id"] == "S2"


def test_two_tenants_use_isolated_credentials():
    a = {
        "channels": {
            "talabat": {
                "mode": "live",
                "api_key": "tenant-a-user",
                "api_secret": "tenant-a-pass",
                "store_id": "A-1",
            }
        }
    }
    b = {
        "channels": {
            "talabat": {
                "mode": "live",
                "api_key": "tenant-b-user",
                "api_secret": "tenant-b-pass",
                "store_id": "B-9",
            }
        }
    }
    assert is_live_mode(a, "talabat") is True
    pa = get_aggregator_port("talabat", restaurant_settings=a)
    pb = get_aggregator_port("talabat", restaurant_settings=b)
    assert isinstance(pa, TalabatAdapter)
    assert isinstance(pb, TalabatAdapter)
    assert pa._cfg["api_key"] == "tenant-a-user"  # noqa: SLF001
    assert pb._cfg["api_key"] == "tenant-b-user"  # noqa: SLF001
    assert pa._cfg["store_id"] == "A-1"  # noqa: SLF001
    assert pb._cfg["store_id"] == "B-9"  # noqa: SLF001
    assert pa is not pb


def test_tenant_webhook_urls_include_slug_and_partner():
    pub, partner = tenant_webhook_urls(
        base_url="https://pos.example",
        public_slug="biryani-house",
        provider="deliveroo",
    )
    assert (
        pub
        == "https://pos.example/api/v1/public/store/biryani-house/aggregators/deliveroo/webhook"
    )
    assert partner == "https://pos.example/api/v1/aggregators/deliveroo/webhook"


@pytest.mark.anyio
async def test_public_slug_webhook_uses_tenant_credentials(
    client, auth_headers, db_session
):
    """Partner pastes tenant URL; HMAC checked against that restaurant only."""
    slug_r = await client.post(
        "/api/v1/aggregators/public-slug",
        headers=auth_headers,
        json={"slug": "mt-cafe"},
    )
    assert slug_r.status_code == 200, slug_r.text
    slug = slug_r.json().get("public_slug") or "mt-cafe"

    put = await client.put(
        "/api/v1/aggregators/channels",
        headers=auth_headers,
        json={
            "channels": {
                "talabat": {
                    "enabled": True,
                    "mode": "mock",
                    "webhook_secret": "tenant-wh-secret",
                }
            }
        },
    )
    assert put.status_code == 200, put.text
    tal = put.json()["channels"]["talabat"]
    assert tal["webhook_secret_set"] is True
    assert tal["webhook_url"]
    assert f"/store/{slug}/aggregators/talabat/webhook" in tal["webhook_url"]

    bad = await client.post(
        f"/api/v1/public/store/{slug}/aggregators/talabat/webhook",
        json={
            "order_id": "MT-1",
            "customer": {"phone": "+971500009999", "name": "MT"},
            "items": [{"name": "Tea", "quantity": 1, "price": "5.00"}],
            "total": "5.00",
        },
        headers={"X-Aggregator-Secret": "wrong"},
    )
    assert bad.status_code == 401

    ok = await client.post(
        f"/api/v1/public/store/{slug}/aggregators/talabat/webhook",
        json={
            "order_id": "MT-2",
            "customer": {"phone": "+971500009998", "name": "MT2"},
            "items": [{"name": "Tea", "quantity": 1, "price": "5.00"}],
            "total": "5.00",
        },
        headers={"X-Aggregator-Secret": "tenant-wh-secret"},
    )
    assert ok.status_code == 201, ok.text
    body = ok.json()
    assert body["restaurant_slug"] == slug
    assert body["source_channel"] == "talabat"
