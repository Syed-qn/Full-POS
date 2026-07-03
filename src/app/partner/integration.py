"""Partner (POS) integration config stored in ``restaurants.settings`` JSONB."""
from __future__ import annotations

from typing import Any

from app.identity.models import Restaurant

_PARTNER_KEYS = (
    "partner",
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
        "partner": (raw.get("partner") or "").strip(),
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


async def provision_partner_integration(
    session, restaurant: Restaurant, partner_slug: str | None = None
) -> str | None:
    """Provision the POS partner integration when a restaurant connects Meta.

    ``partner_slug`` comes from the onboarding link (``?partner=<slug>``):

      * No slug → STANDALONE: the store uses our platform end-to-end (no POS). We
        wire NOTHING — no webhook, no API key. Returns None.
      * A slug (e.g. "cratis", "pos2") → resolve it in the partner registry and, in
        one shot so the partner can talk to the store with zero manual setup:
          - us -> POS: point the store at THAT partner's webhook (url + shared
            secret), enabled; skipped if the partner has no endpoint configured yet
            or the store was already pointed at a partner.
          - POS -> us: mint this store's own API key (only if it has no active one),
            labelled + tagged by partner, and return the full key ONCE (hash-only
            stored). Returns None if a key already exists.

    Best-effort on the webhook wiring; the API key is the important artefact. Caller
    commits.
    """
    from sqlalchemy import func, select

    from app.partner.keys import generate_api_key
    from app.partner.models import PartnerApiKey
    from app.partner.registry import normalize_slug, resolve_partner

    slug = normalize_slug(partner_slug, default="")
    if not slug:
        # Standalone restaurant — no partner, nothing to provision.
        return None

    ref = resolve_partner(slug)

    # Tag the store with its partner (idempotent).
    apply_partner_settings(restaurant, {"partner": ref.slug})

    # us -> POS: wire this partner's webhook, but only if the store isn't already
    # pointed at one (a re-onboard or a manually-configured store keeps its endpoint).
    if ref.webhook_url and not partner_settings(restaurant)["partner_webhook_url"]:
        patch: dict[str, Any] = {
            "partner_enabled": True,
            "partner_webhook_url": ref.webhook_url,
        }
        if ref.webhook_secret:
            patch["partner_webhook_secret"] = ref.webhook_secret
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
            label=f"{ref.name} POS",
            key_prefix=prefix,
            key_hash=key_hash,
            partner=ref.slug,
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