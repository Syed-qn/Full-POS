"""Per-restaurant Meta / WhatsApp connection config, stored in restaurants.settings.

Onboarding page writes these; the WhatsApp/catalog layer will read them with a
fallback to the global env values (so restaurants not yet onboarded keep working
on the shared Meta app). Keys mirror the global settings in app/config.py.
"""
from __future__ import annotations

from typing import Any

from app.identity.models import Restaurant

_META_KEYS = (
    "wa_phone_number_id",
    "wa_business_account_id",
    "wa_access_token",
    "catalog_id",
)


def meta_settings(restaurant: Restaurant) -> dict[str, Any]:
    """Return this restaurant's Meta connection config (empty strings if unset)."""
    raw = restaurant.settings or {}
    return {
        "wa_phone_number_id": (raw.get("wa_phone_number_id") or "").strip(),
        "wa_business_account_id": (raw.get("wa_business_account_id") or "").strip(),
        "wa_access_token": (raw.get("wa_access_token") or "").strip(),
        "catalog_id": (raw.get("catalog_id") or "").strip(),
    }


def apply_meta_settings(restaurant: Restaurant, patch: dict[str, Any]) -> dict[str, Any]:
    """Merge a Meta-config patch into restaurant.settings; return the new snapshot."""
    settings = dict(restaurant.settings or {})
    for key in _META_KEYS:
        if key not in patch or patch[key] is None:
            continue
        val = patch[key]
        if isinstance(val, str):
            val = val.strip()
        settings[key] = val
    restaurant.settings = settings
    return meta_settings(restaurant)


def meta_connected(restaurant: Restaurant) -> bool:
    """True when the restaurant has its own WhatsApp number + token configured."""
    cfg = meta_settings(restaurant)
    return bool(cfg["wa_phone_number_id"] and cfg["wa_access_token"])
