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


async def provision_partner_integration(session, restaurant: Restaurant) -> str | None:
    """Auto-provision the POS partner integration when a restaurant connects Meta.

    Two directions, wired in one shot so the partner (Cratis) can talk to the store
    with zero manual setup:

      * POS -> us: mint this restaurant's own API key (if it has no active one) and
        return the full key ONCE (only the hash is stored) so the caller can surface
        it for the partner. Returns None if a key already exists.
      * us -> POS: point the store at the platform's single global webhook endpoint
        (``partner_webhook_url`` + shared ``partner_webhook_secret`` from settings) and
        enable partner delivery. Idempotent; skipped when no global URL is configured.

    Best-effort on the webhook wiring; the API key is the important artefact. Caller
    commits.
    """
    from sqlalchemy import func, select

    from app.config import get_settings
    from app.partner.keys import generate_api_key
    from app.partner.models import PartnerApiKey

    settings = get_settings()

    # us -> POS: wire the DEFAULT partner's single-endpoint webhook, but only if this
    # store hasn't already been pointed at a partner. Per-restaurant webhook config is
    # the multi-partner mechanism — a store served by a different POS keeps its own
    # endpoint; the global default just saves setup for the majority partner.
    webhook_url = (settings.partner_webhook_url or "").strip()
    if webhook_url and not partner_settings(restaurant)["partner_webhook_url"]:
        patch: dict[str, Any] = {
            "partner_enabled": True,
            "partner_webhook_url": webhook_url,
        }
        secret = settings.partner_webhook_secret.get_secret_value().strip()
        if secret:
            patch["partner_webhook_secret"] = secret
        apply_partner_settings(restaurant, patch)

    # POS -> us: mint a key only if the store has no active one (idempotent on reconnect).
    active = await session.scalar(
        select(func.count())
        .select_from(PartnerApiKey)
        .where(
            PartnerApiKey.restaurant_id == restaurant.id,
            PartnerApiKey.revoked_at.is_(None),
        )
    )
    if active:
        return None
    full_key, prefix, key_hash = generate_api_key()
    session.add(
        PartnerApiKey(
            restaurant_id=restaurant.id,
            label="POS Integration",
            key_prefix=prefix,
            key_hash=key_hash,
        )
    )
    return full_key


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