
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
    monkeypatch.setattr(meta_embed, "subscribe_app_to_waba", fake_subscribe)
    monkeypatch.setattr(meta_embed, "fetch_waba_catalog_id", fake_catalog)
    monkeypatch.setattr(meta_embed, "fetch_display_phone_number", fake_display)

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
    assert body["catalog_id"] == "CAT-AUTO-1"  # auto-detected from the WABA
    assert body["connected"] is True
    assert "wa_access_token" not in body  # secret never returned

    # The routing phone is reconciled to the REAL connected number (normalized),
    # not whatever was typed at signup — closing the inbound-mismatch gap.
    me = await client.get("/api/v1/me", headers=auth_headers)
    assert me.json()["phone"] == "+971550009999"


async def test_meta_connect_auto_creates_catalog_when_none(
    client, auth_headers, monkeypatch
):
    """A new restaurant with no catalog gets one auto-provisioned during connect:
    resolve owner business → create catalog → connect to WABA → store its id."""
    from app.identity import meta_embed

    calls = {}

    async def fake_exchange(code):
        return "EAA-token"

    async def fake_subscribe(waba_id, token):
        return True

    async def fake_catalog(waba_id, token):
        return ""  # WABA has NO linked catalog yet

    async def fake_owner(waba_id, token):
        assert waba_id == "WABA-NEW"
        return "BIZ-77"

    async def fake_create(business_id, token, *, name):
        assert business_id == "BIZ-77"
        calls["created_name"] = name
        return "CAT-NEW-9"

    async def fake_connect(waba_id, catalog_id, token):
        calls["connected"] = (waba_id, catalog_id)
        return True

    async def fake_display(pid, token):
        return ""

    monkeypatch.setattr(meta_embed, "exchange_code_for_token", fake_exchange)
    monkeypatch.setattr(meta_embed, "subscribe_app_to_waba", fake_subscribe)
    monkeypatch.setattr(meta_embed, "fetch_waba_catalog_id", fake_catalog)
    monkeypatch.setattr(meta_embed, "fetch_waba_owner_business", fake_owner)
    monkeypatch.setattr(meta_embed, "create_owned_catalog", fake_create)
    monkeypatch.setattr(meta_embed, "connect_catalog_to_waba", fake_connect)
    monkeypatch.setattr(meta_embed, "fetch_display_phone_number", fake_display)

    r = await client.post(
        "/api/v1/onboarding/meta-connect",
        headers=auth_headers,
        json={"code": "C", "phone_number_id": "PID-NEW", "waba_id": "WABA-NEW"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["catalog_id"] == "CAT-NEW-9"  # the freshly created + linked catalog
    assert calls["connected"] == ("WABA-NEW", "CAT-NEW-9")
    assert "WhatsApp" in calls["created_name"]  # named after the restaurant


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