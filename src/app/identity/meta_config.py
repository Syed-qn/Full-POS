"""Per-restaurant Meta / WhatsApp connection config, stored in restaurants.settings.

The onboarding page writes these; the WhatsApp/catalog layer reads them, preferring
the restaurant's own connected number. Connecting Meta is compulsory (onboarding
cannot finish without it), and in production the global env WA values are left EMPTY
— so there is no shared number: a connected restaurant sends from its own creds, and
an unconnected one (blocked by the gate anyway) has no number to fall back to. Keys
mirror the global settings in app/config.py.
"""
from __future__ import annotations

from typing import Any

from app.identity.models import Restaurant

_META_KEYS = (
    "wa_phone_number_id",
    "wa_business_account_id",
    "wa_access_token",
    "catalog_id",
    # 2FA PIN used to register the number on the Cloud API. Persisted so a reconnect
    # re-registers with the SAME pin (Meta rejects a new pin on a number that already
    # has 2FA). Never surfaced in MetaConfigOut.
    "wa_2fa_pin",
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


def disconnect_meta(restaurant: Restaurant) -> dict[str, Any]:
    """Clear this restaurant's WhatsApp connection and re-open onboarding.

    Removes the stored number/token/WABA and flips onboarding_complete off, so the
    onboarding gate re-triggers and the manager must reconnect Meta to operate
    again. Menu/catalogue/data are untouched. Caller commits.
    """
    settings = dict(restaurant.settings or {})
    # catalog_id is part of the Meta connection (a pointer to that account's catalog),
    # so clear it too — otherwise reconnecting a different number/business that has no
    # catalog leaves a stale catalog_id, since connect only overwrites a catalog_id it
    # finds, never clears one it doesn't.
    for key in (
        "wa_phone_number_id", "wa_business_account_id", "wa_access_token",
        "catalog_id", "wa_2fa_pin",
    ):
        settings.pop(key, None)
    settings["onboarding_complete"] = False
    restaurant.settings = settings
    return meta_settings(restaurant)


def meta_connected(restaurant: Restaurant) -> bool:
    """True when the restaurant has its own WhatsApp number + token configured."""
    cfg = meta_settings(restaurant)
    return bool(cfg["wa_phone_number_id"] and cfg["wa_access_token"])


def resolve_send_creds(restaurant: Restaurant | None) -> tuple[str, str]:
    """Return (phone_number_id, access_token) to send WhatsApp for this restaurant.

    Prefers the restaurant's own connected Meta number. Falls back to the global env
    values, which in production are EMPTY — so an unconnected restaurant resolves to
    blank creds (send fails safe; it can't operate anyway, being blocked by the
    onboarding gate). No shared number is ever used across restaurants.
    """
    from app.config import get_settings

    settings = get_settings()
    cfg = meta_settings(restaurant) if restaurant is not None else {}
    pid = cfg.get("wa_phone_number_id") or settings.wa_phone_number_id
    token = cfg.get("wa_access_token") or settings.wa_access_token.get_secret_value()
    return pid, token
