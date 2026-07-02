from decimal import Decimal

import pytest

from app.identity.service import get_onboarding_status

pytestmark_asyncio = pytest.mark.asyncio


def test_resolve_send_creds_prefers_connected_restaurant():
    from app.identity.meta_config import resolve_send_creds

    class _R:
        settings = {"wa_phone_number_id": "PID-own", "wa_access_token": "TOK-own"}

    pid, token = resolve_send_creds(_R())
    assert pid == "PID-own"
    assert token == "TOK-own"


def test_resolve_send_creds_falls_back_to_env_when_not_connected():
    from app.identity.meta_config import resolve_send_creds

    class _R:
        settings = {}

    # Env WA values are empty in production, so an unconnected restaurant resolves
    # to blank creds (no shared number) — here we only assert the types/shape.
    pid, token = resolve_send_creds(_R())
    assert isinstance(pid, str)
    assert isinstance(token, str)


async def test_meta_config_save_and_read(client, auth_headers):
    """Onboarding page saves the restaurant's Meta connection; token never echoed."""
    empty = await client.get("/api/v1/onboarding/meta-config", headers=auth_headers)
    assert empty.status_code == 200
    assert empty.json()["connected"] is False

    saved = await client.patch(
        "/api/v1/onboarding/meta-config",
        headers=auth_headers,
        json={
            "wa_phone_number_id": "123456789",
            "wa_business_account_id": "waba-1",
            "wa_access_token": "EAAsecret-token",
            "catalog_id": "CAT-1",
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["wa_phone_number_id"] == "123456789"
    assert body["wa_business_account_id"] == "waba-1"
    assert body["catalog_id"] == "CAT-1"
    assert body["wa_access_token_set"] is True
    assert body["connected"] is True
    assert "wa_access_token" not in body  # secret never returned

    # Partial update keeps existing values.
    patched = await client.patch(
        "/api/v1/onboarding/meta-config",
        headers=auth_headers,
        json={"catalog_id": "CAT-2"},
    )
    assert patched.json()["catalog_id"] == "CAT-2"
    assert patched.json()["wa_phone_number_id"] == "123456789"
    assert patched.json()["connected"] is True


async def test_meta_embed_config_disabled_without_app(client, auth_headers):
    """No tech-provider app configured in tests → popup disabled, UI uses manual."""
    r = await client.get("/api/v1/onboarding/meta-embed-config", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False  # no config_id in test env → popup off
    assert body["config_id"] == ""
    assert body["graph_version"]  # e.g. v21.0


async def test_meta_connect_exchanges_code_and_stores_creds(
    client, auth_headers, monkeypatch
):
    """Embedded Signup: code → token exchange → per-restaurant creds; token hidden."""
    from app.identity import meta_embed

    async def fake_exchange(code):
        assert code == "CODE-123"
        return "EAA-business-token"

    async def fake_subscribe(waba_id, token):
        assert waba_id == "WABA-9"
        assert token == "EAA-business-token"
        return True

    monkeypatch.setattr(meta_embed, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(meta_embed, "subscribe_app_to_waba", fake_subscribe)

    r = await client.post(
        "/api/v1/onboarding/meta-connect",
        headers=auth_headers,
        json={"code": "CODE-123", "phone_number_id": "PID-9", "waba_id": "WABA-9"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["wa_phone_number_id"] == "PID-9"
    assert body["wa_business_account_id"] == "WABA-9"
    assert body["wa_access_token_set"] is True
    assert body["connected"] is True
    assert "wa_access_token" not in body  # secret never returned


async def test_meta_connect_surfaces_exchange_failure(
    client, auth_headers, monkeypatch
):
    """A failed code exchange returns 400, not 500, and stores nothing."""
    from app.identity import meta_embed

    async def boom(code):
        raise meta_embed.MetaEmbedError("token exchange failed (HTTP 400): bad code")

    monkeypatch.setattr(meta_embed, "exchange_code_for_token", boom)

    r = await client.post(
        "/api/v1/onboarding/meta-connect",
        headers=auth_headers,
        json={"code": "BAD", "phone_number_id": "PID-9", "waba_id": "WABA-9"},
    )
    assert r.status_code == 400
    # Nothing stored → still not connected.
    cfg = await client.get("/api/v1/onboarding/meta-config", headers=auth_headers)
    assert cfg.json()["connected"] is False


async def test_new_signup_not_complete_without_menu(db_session, restaurant):
    restaurant.settings = {**restaurant.settings, "onboarding_complete": False}
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["complete"] is False
    assert st["has_menu"] is False


async def test_catalog_synced_false_when_dish_only_remains(db_session, restaurant):
    from app.catalog.models import CatalogProduct
    from app.menu.models import Dish, Menu

    restaurant.settings = {
        **restaurant.settings,
        "catalog_id": "CAT1",
        "onboarding_complete": False,
    }
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, name="Biryani",
        price_aed=Decimal("30"), is_available=True,
        name_normalized="biryani", catalog_retailer_id="r1",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, name="Mint",
        price_aed=Decimal("12"), is_available=True,
        name_normalized="mint",
    ))
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="r1", name="Biryani",
        price_aed=Decimal("30"), is_active=True, raw={},
    ))
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["catalog_synced"] is False
    assert st["complete"] is False


async def test_legacy_restaurant_with_menu_skips_onboarding(db_session, restaurant):
    from app.menu.models import Menu

    restaurant.settings = {k: v for k, v in restaurant.settings.items() if k != "onboarding_complete"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["complete"] is True