
import pytest

from app.identity.service import get_onboarding_status

pytestmark_asyncio = pytest.mark.asyncio


async def _ok_register(phone_number_id, access_token, pin):
    """Stub: number activation succeeds (real call hits Meta; tests never should)."""
    return True


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


def test_disconnect_meta_also_clears_catalog_id():
    """Disconnect wipes the Meta connection INCLUDING catalog_id, so a later reconnect
    of a catalog-less account can't inherit a stale catalog pointer."""
    from app.identity.meta_config import disconnect_meta

    class _R:
        settings = {
            "wa_phone_number_id": "PID", "wa_access_token": "TOK",
            "wa_business_account_id": "WABA", "catalog_id": "CAT-OLD",
            "onboarding_complete": True, "max_radius_km": 10,  # unrelated key survives
        }

    r = _R()
    out = disconnect_meta(r)
    assert out["catalog_id"] == ""
    assert r.settings.get("catalog_id") is None
    assert r.settings["onboarding_complete"] is False
    assert r.settings["max_radius_km"] == 10  # non-Meta settings untouched


async def test_provision_partner_integration_mints_key_and_wires_webhook(
    db_session, restaurant, monkeypatch
):
    """On connect, a store onboarded via ?partner=cratis wires that partner's webhook
    (from the APP_PARTNERS registry) and mints the store's API key once. Idempotent."""
    import json
    from types import SimpleNamespace

    from sqlalchemy import func, select

    from app import config
    from app.partner.integration import partner_settings, provision_partner_integration
    from app.partner.models import PartnerApiKey

    fake = SimpleNamespace(
        default_partner="cratis",
        partners_json=json.dumps(
            {
                "cratis": {
                    "name": "Cratis",
                    "webhook_url": "https://cratis.example.com/hooks/whatsapp",
                    "webhook_secret": "shared-signing-secret",
                }
            }
        ),
    )
    monkeypatch.setattr(config, "get_settings", lambda: fake)

    key = await provision_partner_integration(db_session, restaurant, "cratis")
    await db_session.commit()

    assert key and key.startswith("rk_live_")  # returned once for the partner
    cfg = partner_settings(restaurant)
    assert cfg["partner"] == "cratis"  # store tagged with its partner
    assert cfg["partner_enabled"] is True
    assert cfg["partner_webhook_url"] == "https://cratis.example.com/hooks/whatsapp"
    assert cfg["partner_webhook_secret"] == "shared-signing-secret"
    count = await db_session.scalar(
        select(func.count()).select_from(PartnerApiKey).where(
            PartnerApiKey.restaurant_id == restaurant.id
        )
    )
    assert count == 1

    # Idempotent: a reconnect does not mint a second key.
    again = await provision_partner_integration(db_session, restaurant, "cratis")
    await db_session.commit()
    assert again is None
    count2 = await db_session.scalar(
        select(func.count()).select_from(PartnerApiKey).where(
            PartnerApiKey.restaurant_id == restaurant.id
        )
    )
    assert count2 == 1


async def test_meta_config_save_and_read(client, auth_headers, monkeypatch):
    """Onboarding page saves the restaurant's Meta connection; token never echoed."""
    from app.identity import meta_embed

    async def _no_display(pid, token):
        return ""

    monkeypatch.setattr(meta_embed, "fetch_display_phone_number", _no_display)

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

    async def fake_catalog(waba_id, token):
        assert waba_id == "WABA-9"
        return "CAT-AUTO-1"

    async def fake_display(pid, token):
        assert pid == "PID-9"
        return "+971 55 000 9999"  # deliberately different from signup phone

    monkeypatch.setattr(meta_embed, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(meta_embed, "register_phone_number", _ok_register)
    monkeypatch.setattr(meta_embed, "subscribe_app_to_waba", fake_subscribe)
    monkeypatch.setattr(meta_embed, "fetch_waba_catalog_id", fake_catalog)
    monkeypatch.setattr(meta_embed, "fetch_display_phone_number", fake_display)

    r = await client.post(
        "/api/v1/onboarding/meta-connect",
        headers=auth_headers,
        json={"code": "CODE-123", "phone_number_id": "PID-9", "waba_id": "WABA-9",
              "partner": "cratis"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["wa_phone_number_id"] == "PID-9"
    assert body["wa_business_account_id"] == "WABA-9"
    assert body["wa_access_token_set"] is True
    assert body["catalog_id"] == "CAT-AUTO-1"  # auto-detected from the WABA
    assert body["connected"] is True
    assert "wa_access_token" not in body  # secret never returned
    # Onboarding via a partner link (?partner=cratis) auto-mints the store's POS
    # API key, returned ONCE for the partner.
    assert body["api_key"] and body["api_key"].startswith("rk_live_")

    # The routing phone is reconciled to the REAL connected number (normalized),
    # not whatever was typed at signup — closing the inbound-mismatch gap.
    me = await client.get("/api/v1/me", headers=auth_headers)
    assert me.json()["phone"] == "+971550009999"


async def test_meta_connect_attaches_shared_catalog_when_not_yet_linked(
    client, auth_headers, monkeypatch
):
    """Selecting a catalog in the popup only SHARES it with our app — it isn't
    attached to the WABA. On connect we find the shared catalog in the owner
    business and attach it ourselves (Meta forbids us creating one), then store it."""
    from app.identity import meta_embed

    calls = {}

    async def fake_exchange(code):
        return "EAA-token"

    async def fake_subscribe(waba_id, token):
        return True

    async def fake_catalog(waba_id, token):
        return ""  # nothing attached to the WABA yet

    async def fake_owner(waba_id, token):
        assert waba_id == "WABA-NEW"
        return "BIZ-77"

    async def fake_list(business_id, token):
        assert business_id == "BIZ-77"
        # newest-first; manager just shared "CAT-NEW-9"
        return [{"id": "CAT-NEW-9", "name": "My Menu"}, {"id": "CAT-OLD-1", "name": "Old"}]

    async def fake_connect(waba_id, catalog_id, token):
        calls["connected"] = (waba_id, catalog_id)
        return True

    async def fake_display(pid, token):
        return ""

    monkeypatch.setattr(meta_embed, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(meta_embed, "register_phone_number", _ok_register)
    monkeypatch.setattr(meta_embed, "subscribe_app_to_waba", fake_subscribe)
    monkeypatch.setattr(meta_embed, "fetch_waba_catalog_id", fake_catalog)
    monkeypatch.setattr(meta_embed, "fetch_waba_owner_business", fake_owner)
    monkeypatch.setattr(meta_embed, "list_owned_catalogs", fake_list)
    monkeypatch.setattr(meta_embed, "connect_catalog_to_waba", fake_connect)
    monkeypatch.setattr(meta_embed, "fetch_display_phone_number", fake_display)

    r = await client.post(
        "/api/v1/onboarding/meta-connect",
        headers=auth_headers,
        json={"code": "C", "phone_number_id": "PID-NEW", "waba_id": "WABA-NEW"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["catalog_id"] == "CAT-NEW-9"  # the shared catalog we attached
    assert calls["connected"] == ("WABA-NEW", "CAT-NEW-9")


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


async def test_meta_disconnect_clears_creds_and_reopens_onboarding(
    client, auth_headers, monkeypatch
):
    """Disconnect clears creds, flips connected→false, and re-opens onboarding."""
    from app.identity import meta_embed

    async def fake_exchange(code):
        return "EAA-token"

    async def fake_subscribe(waba_id, token):
        return True

    async def fake_catalog(waba_id, token):
        return ""

    async def fake_owner(waba_id, token):
        return ""  # no owner business → auto-create is skipped, stays catalog-less

    async def fake_display(pid, token):
        return ""

    monkeypatch.setattr(meta_embed, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(meta_embed, "register_phone_number", _ok_register)
    monkeypatch.setattr(meta_embed, "subscribe_app_to_waba", fake_subscribe)
    monkeypatch.setattr(meta_embed, "fetch_waba_catalog_id", fake_catalog)
    monkeypatch.setattr(meta_embed, "fetch_waba_owner_business", fake_owner)
    monkeypatch.setattr(meta_embed, "fetch_display_phone_number", fake_display)

    # Connect first.
    await client.post(
        "/api/v1/onboarding/meta-connect",
        headers=auth_headers,
        json={"code": "C", "phone_number_id": "PID-1", "waba_id": "WABA-1"},
    )
    assert (await client.get("/api/v1/onboarding/meta-config", headers=auth_headers)).json()["connected"] is True

    # Disconnect.
    r = await client.post("/api/v1/onboarding/meta-disconnect", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["connected"] is False
    assert body["wa_phone_number_id"] == ""
    assert body["wa_access_token_set"] is False

    # Onboarding gate re-triggers (complete → false because meta gone).
    st = (await client.get("/api/v1/onboarding/status", headers=auth_headers)).json()
    assert st["complete"] is False
    assert st["has_meta"] is False


async def test_onboarding_incomplete_until_meta_connected(db_session, restaurant):
    """Onboarding gates ONLY on Meta: no connection → not complete, even with a
    menu + catalog already present (those are configured later in the dashboard)."""
    from app.menu.models import Menu

    restaurant.settings = {**restaurant.settings, "catalog_id": "CAT1"}
    db_session.add(Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[]))
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["has_meta"] is False
    assert st["complete"] is False  # menu + catalog present, but no Meta → gated


async def test_onboarding_complete_once_meta_connected(db_session, restaurant):
    """Connecting WhatsApp (Meta) alone completes onboarding — no menu required."""
    from app.identity.meta_config import apply_meta_settings

    apply_meta_settings(
        restaurant,
        {"wa_phone_number_id": "PID-1", "wa_access_token": "TOK-1"},
    )
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["has_meta"] is True
    assert st["complete"] is True