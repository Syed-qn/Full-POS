"""Multi-partner registry: resolve a partner slug + provision by partner.

Onboarding tags a store with ?partner=<slug>. No slug = standalone (no POS):
nothing wired. A slug wires THAT partner's webhook + a partner-labelled key.
"""
import json
from types import SimpleNamespace

from pydantic import SecretStr
from sqlalchemy import func, select

from app.identity.models import Restaurant
from app.partner.models import PartnerApiKey
from app.partner.registry import normalize_slug, resolve_partner


def _settings(**kw):
    base = dict(
        default_partner="cratis",
        partners_json="",
        partner_webhook_url="",
        partner_webhook_secret=SecretStr(""),
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── registry resolver (pure, no DB) ──────────────────────────────────────────
def test_resolve_default_partner_uses_toplevel_fields():
    s = _settings(
        partner_webhook_url="https://cratis.example.com/hooks",
        partner_webhook_secret=SecretStr("sec"),
    )
    ref = resolve_partner("cratis", s)
    assert ref.slug == "cratis"
    assert ref.webhook_url == "https://cratis.example.com/hooks"
    assert ref.webhook_secret == "sec"


def test_resolve_registry_partner():
    s = _settings(
        partners_json=json.dumps(
            {"pos2": {"name": "Acme", "webhook_url": "https://acme/h", "webhook_secret": "k2"}}
        )
    )
    ref = resolve_partner("pos2", s)
    assert ref.slug == "pos2"
    assert ref.name == "Acme"
    assert ref.webhook_url == "https://acme/h"
    assert ref.webhook_secret == "k2"


def test_resolve_unknown_slug_has_no_webhook():
    ref = resolve_partner("ghost", _settings())
    assert ref.slug == "ghost"
    assert ref.webhook_url == ""  # unconfigured partner → nothing to wire


def test_normalize_slug():
    assert normalize_slug("  Cratis ", default="x") == "cratis"
    assert normalize_slug("", default="x") == "x"
    assert normalize_slug("po$s 2!", default="x") == "pos2"


# ── provision by partner (DB) ────────────────────────────────────────────────
async def _restaurant(db_session) -> Restaurant:
    return await db_session.scalar(
        select(Restaurant).where(Restaurant.phone == "+971501234567")
    )


async def _key_count(db_session, restaurant_id) -> int:
    return await db_session.scalar(
        select(func.count()).select_from(PartnerApiKey).where(
            PartnerApiKey.restaurant_id == restaurant_id
        )
    )


async def test_provision_standalone_wires_nothing(db_session, auth_headers, monkeypatch):
    """No partner slug → standalone: no webhook, no key, no partner tag."""
    from app import config
    from app.partner.integration import partner_settings, provision_partner_integration

    monkeypatch.setattr(config, "get_settings", lambda: _settings())
    rest = await _restaurant(db_session)

    key = await provision_partner_integration(db_session, rest, None)
    await db_session.commit()

    assert key is None
    cfg = partner_settings(rest)
    assert cfg["partner"] == ""
    assert cfg["partner_enabled"] is False
    assert cfg["partner_webhook_url"] == ""
    assert await _key_count(db_session, rest.id) == 0


async def test_provision_registry_partner_wires_and_labels(
    db_session, auth_headers, monkeypatch
):
    """?partner=pos2 → wire pos2's webhook + mint a pos2-labelled/tagged key."""
    from app import config
    from app.partner.integration import partner_settings, provision_partner_integration

    monkeypatch.setattr(
        config,
        "get_settings",
        lambda: _settings(
            partners_json=json.dumps(
                {"pos2": {"name": "Acme", "webhook_url": "https://acme/h", "webhook_secret": "k2"}}
            )
        ),
    )
    rest = await _restaurant(db_session)

    key = await provision_partner_integration(db_session, rest, "pos2")
    await db_session.commit()

    assert key and key.startswith("rk_live_")
    cfg = partner_settings(rest)
    assert cfg["partner"] == "pos2"
    assert cfg["partner_enabled"] is True
    assert cfg["partner_webhook_url"] == "https://acme/h"
    assert cfg["partner_webhook_secret"] == "k2"

    row = await db_session.scalar(
        select(PartnerApiKey).where(PartnerApiKey.restaurant_id == rest.id)
    )
    assert row.partner == "pos2"
    assert row.label == "Acme POS"
