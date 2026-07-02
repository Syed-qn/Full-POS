"""Partner (POS) integration config stored in ``restaurants.settings`` JSONB."""
from __future__ import annotations

from typing import Any

from app.identity.models import Restaurant

_PARTNER_KEYS = (
    "partner_enabled",
    "partner_webhook_url",
    "partner_webhook_secret",
    "pos_store_id",
    "pos_order_push_mode",
)


def partner_settings(restaurant: Restaurant) -> dict[str, Any]:
    """Return partner-related settings with defaults."""
    raw = restaurant.settings or {}
    return {
        "partner_enabled": bool(raw.get("partner_enabled")),
        "partner_webhook_url": (raw.get("partner_webhook_url") or "").strip(),
        "partner_webhook_secret": (raw.get("partner_webhook_secret") or "").strip(),
        "pos_store_id": (raw.get("pos_store_id") or "").strip(),
        "pos_order_push_mode": (raw.get("pos_order_push_mode") or "webhook").strip(),
    }


def apply_partner_settings(restaurant: Restaurant, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge partner config patch into restaurant.settings; return new snapshot."""
    settings = dict(restaurant.settings or {})
    for key in _PARTNER_KEYS:
        if key not in patch or patch[key] is None:
            continue
        val = patch[key]
        if isinstance(val, str):
            val = val.strip()
        settings[key] = val
    restaurant.settings = settings
    return partner_settings(restaurant)


def partner_webhook_config(restaurant: Restaurant) -> tuple[str | None, str | None]:
    """Return (target_url, secret) when partner webhooks are enabled, else (None, None)."""
    cfg = partner_settings(restaurant)
    if not cfg["partner_enabled"]:
        return None, None
    url = cfg["partner_webhook_url"]
    if not url:
        return None, None
    secret = cfg["partner_webhook_secret"] or None
    return url, secret