"""Per-restaurant channel configuration (pause, commission, public links)."""

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
    {"talabat", "deliveroo", "careem", "ubereats", "noon", "zomato"}
)

_DEFAULT_CHANNEL = {
    "enabled": False,
    "accepting": True,
    "commission_pct": 0.0,
    "mode": "mock",  # mock | live
    "api_key": None,
    "api_secret": None,
    "webhook_secret": None,
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


def set_channels_config(restaurant, updates: dict[str, Any]) -> dict[str, dict]:
    """Merge channel updates into restaurant.settings['channels']."""
    settings = dict(restaurant.settings) if isinstance(restaurant.settings, dict) else {}
    channels = dict(settings.get("channels") or {})
    for key, patch in updates.items():
        if key not in CHANNEL_KEYS:
            continue
        if not isinstance(patch, dict):
            continue
        current = dict(channels.get(key) or copy.deepcopy(_DEFAULTS[key]))
        current.update(patch)
        channels[key] = current
    settings["channels"] = channels
    restaurant.settings = settings
    return get_channels_config(settings)


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
