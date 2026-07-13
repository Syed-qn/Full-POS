"""Per-restaurant channel configuration (pause, commission, public links).

Multi-tenant SaaS: every restaurant owns ``settings.channels.<provider>`` with
**their** partner credentials (api_key, api_secret, webhook_secret, store_id…).
Factory ``get_aggregator_port(..., restaurant_settings=)`` always reads that
tenant blob — never a global platform key.
"""

from __future__ import annotations

import copy
from typing import Any

# Canonical channel keys for inbox / reports / pause.
CHANNEL_KEYS = (
    "whatsapp",
    "talabat",
    "deliveroo",
    "careem",
    "ubereats",
    "noon",
    "zomato",
    "keeta",
    "website",
    "mobile_app",
    "instagram",
    "google_business",
    "qr",
    "kiosk",
    "call_center",
)

# Aggregator subset that use AggregatorPort.
AGGREGATOR_CHANNELS = frozenset(
    {"talabat", "deliveroo", "careem", "ubereats", "noon", "zomato", "keeta"}
)

# Operator-facing credential field guidance (dashboard).
CREDENTIAL_HINTS: dict[str, str] = {
    "talabat": "DH username → API key, password → API secret, vendor id → Store ID",
    "deliveroo": "API key + API secret/token (Bearer), site_id → Store ID",
    "ubereats": "OAuth client_id → API key, client_secret → API secret, store UUID → Store ID",
    "keeta": "appId → API key, appSecret → API secret, accessToken → Access token, shopId → Store ID",
    "careem": "Middleware API key/secret + Store/channel-link ID; Base URL = middleware host",
    "noon": "Middleware API key/secret + Store/channel-link ID; Base URL = middleware host",
    "zomato": "Partner API key/secret + outlet Store ID (generic live HTTP until brand mapper)",
}

_DEFAULT_CHANNEL = {
    "enabled": False,
    "accepting": True,
    "commission_pct": 0.0,
    "mode": "mock",  # mock | live
    "api_key": None,
    "api_secret": None,
    "webhook_secret": None,
    "access_token": None,
    "store_id": None,
    "base_url": None,
    "order_url": None,
    "slug": None,
}

_DEFAULTS: dict[str, dict] = {
    "whatsapp": {**_DEFAULT_CHANNEL, "enabled": True, "accepting": True},
    "talabat": {**_DEFAULT_CHANNEL, "commission_pct": 25.0},
    "deliveroo": {**_DEFAULT_CHANNEL, "commission_pct": 30.0},
    "careem": {**_DEFAULT_CHANNEL, "commission_pct": 25.0},
    "ubereats": {**_DEFAULT_CHANNEL, "commission_pct": 30.0},
    "noon": {**_DEFAULT_CHANNEL, "commission_pct": 25.0},
    "zomato": {**_DEFAULT_CHANNEL, "commission_pct": 20.0},
    "keeta": {**_DEFAULT_CHANNEL, "commission_pct": 25.0},
    "website": {**_DEFAULT_CHANNEL, "enabled": True, "accepting": True},
    "mobile_app": {**_DEFAULT_CHANNEL, "enabled": True, "accepting": True},
    "instagram": {**_DEFAULT_CHANNEL, "enabled": True},
    "google_business": {**_DEFAULT_CHANNEL, "enabled": True},
    "qr": {**_DEFAULT_CHANNEL, "enabled": True, "accepting": True},
    "kiosk": {**_DEFAULT_CHANNEL, "enabled": True, "accepting": True},
    "call_center": {**_DEFAULT_CHANNEL, "enabled": True, "accepting": True},
}


def get_channels_config(restaurant_settings: dict | None) -> dict[str, dict]:
    raw = (restaurant_settings or {}).get("channels") or {}
    out: dict[str, dict] = {}
    for key in CHANNEL_KEYS:
        base = copy.deepcopy(_DEFAULTS[key])
        override = raw.get(key) if isinstance(raw.get(key), dict) else {}
        base.update({k: v for k, v in override.items() if v is not None})
        out[key] = base
    return out


# Credential keys that may be written once and must not be wiped by empty strings.
_SECRET_KEYS = frozenset({"api_key", "api_secret", "webhook_secret", "access_token"})


def set_channels_config(restaurant, updates: dict[str, Any]) -> dict[str, dict]:
    """Merge channel updates into restaurant.settings['channels'].

    Empty-string secrets are ignored (keep previous) so the dashboard can
    patch non-secret fields without re-sending passwords.
    """
    settings = dict(restaurant.settings) if isinstance(restaurant.settings, dict) else {}
    channels = dict(settings.get("channels") or {})
    for key, patch in updates.items():
        if key not in CHANNEL_KEYS:
            continue
        if not isinstance(patch, dict):
            continue
        current = dict(channels.get(key) or copy.deepcopy(_DEFAULTS[key]))
        cleaned = dict(patch)
        for sk in _SECRET_KEYS:
            if sk in cleaned and (cleaned[sk] is None or str(cleaned[sk]).strip() == ""):
                cleaned.pop(sk)
        current.update(cleaned)
        channels[key] = current
    settings["channels"] = channels
    restaurant.settings = settings
    return get_channels_config(settings)


def tenant_webhook_urls(
    *,
    base_url: str,
    public_slug: str | None,
    provider: str,
) -> tuple[str | None, str]:
    """Return (public slug webhook, partner API-key webhook) for one provider."""
    base = (base_url or "").rstrip("/")
    partner = f"{base}/api/v1/aggregators/{provider}/webhook"
    public = None
    if public_slug:
        public = f"{base}/api/v1/public/store/{public_slug}/aggregators/{provider}/webhook"
    return public, partner


def channel_is_accepting(restaurant_settings: dict | None, channel: str) -> bool:
    """Whether inbound orders may land on this channel.

    Unconfigured aggregator channels accept by default (mock integrations /
    partner webhooks work out of the box). Explicit ``enabled=False`` or
    ``accepting=False`` blocks. Direct channels (website/qr/…) follow defaults
    in ``_DEFAULTS`` (enabled True).
    """
    raw = (restaurant_settings or {}).get("channels") or {}
    explicit = raw.get(channel) if isinstance(raw, dict) else None
    cfg = get_channels_config(restaurant_settings).get(channel) or {}

    # Explicit disable wins.
    if isinstance(explicit, dict) and explicit.get("enabled") is False:
        return False
    if isinstance(explicit, dict) and explicit.get("accepting") is False:
        return False

    # Never configured: aggregators + whatsapp accept (ops can pause later).
    if not isinstance(explicit, dict) or not explicit:
        if channel in AGGREGATOR_CHANNELS or channel == "whatsapp":
            return True
        return bool(cfg.get("enabled", False)) and bool(cfg.get("accepting", True))

    if not cfg.get("enabled", False):
        return False
    return bool(cfg.get("accepting", True))


def commission_pct_for(restaurant_settings: dict | None, channel: str) -> float:
    cfg = get_channels_config(restaurant_settings).get(channel) or {}
    return float(cfg.get("commission_pct") or 0.0)


def order_channel_key(order) -> str:
    """Map an order row to a channel key for reporting/inbox."""
    src = getattr(order, "aggregator_source", None)
    if src:
        return str(src).lower()
    ot = (getattr(order, "order_type", None) or "delivery").lower()
    if ot == "delivery":
        return "whatsapp"
    if ot == "online":
        return "website"
    if ot == "qr":
        return "qr"
    if ot == "tableside":
        return "kiosk"
    if ot == "aggregator":
        return "talabat"  # generic
    return ot
