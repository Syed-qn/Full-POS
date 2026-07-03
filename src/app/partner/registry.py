"""Multi-partner registry — resolve a partner slug to its webhook config.

Launch is single-partner (Cratis), so the DEFAULT partner uses the top-level
``partner_webhook_url`` / ``partner_webhook_secret`` settings. Additional POS
partners are added as a JSON map in ``APP_PARTNERS`` without any code change:

    APP_PARTNERS={"pos2": {"name": "Acme POS",
                            "webhook_url": "https://acme.example.com/hooks",
                            "webhook_secret": "..."}}

A restaurant is tagged with its partner slug at onboarding (``?partner=<slug>``);
each store then wires to *that* partner's webhook + a key labelled by partner, so
partners never collide. Unknown/blank slug falls back to ``default_partner``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

_SLUG_RE = re.compile(r"[^a-z0-9_-]")


@dataclass(frozen=True)
class PartnerRef:
    slug: str
    name: str
    webhook_url: str
    webhook_secret: str


def normalize_slug(slug: str | None, *, default: str) -> str:
    """Lowercase, strip, keep only [a-z0-9_-]; blank → default."""
    cleaned = _SLUG_RE.sub("", (slug or "").strip().lower())
    return cleaned or default


def _parse_registry(raw: str) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def resolve_partner(slug: str | None, settings=None) -> PartnerRef:
    """Resolve a partner slug to its webhook config.

    Resolution order:
      1. slug present in the APP_PARTNERS registry → use that entry.
      2. slug == default_partner (or blank/unknown) → the top-level
         partner_webhook_url / partner_webhook_secret (the default partner).

    Uses getattr with defaults so a minimal settings stub (tests) still works.
    """
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    default = (getattr(settings, "default_partner", "") or "cratis").strip().lower()
    registry = _parse_registry(getattr(settings, "partners_json", "") or "")
    slug = normalize_slug(slug, default=default)

    entry = registry.get(slug)
    if isinstance(entry, dict):
        return PartnerRef(
            slug=slug,
            name=str(entry.get("name") or slug),
            webhook_url=str(entry.get("webhook_url") or "").strip(),
            webhook_secret=str(entry.get("webhook_secret") or "").strip(),
        )

    # The default_partner slug owns the legacy top-level partner_webhook_url/secret
    # (so the majority partner needs no APP_PARTNERS entry). This is NOT an
    # untagged fallback — an untagged store is standalone and never reaches here.
    if slug == default:
        secret = getattr(settings, "partner_webhook_secret", None)
        secret_val = (
            secret.get_secret_value() if hasattr(secret, "get_secret_value") else (secret or "")
        )
        return PartnerRef(
            slug=default,
            name=default,
            webhook_url=(getattr(settings, "partner_webhook_url", "") or "").strip(),
            webhook_secret=(secret_val or "").strip(),
        )

    # Known-shape but unconfigured partner slug: tag the store, but there's no
    # webhook endpoint to wire yet (configure it in APP_PARTNERS to enable push).
    return PartnerRef(slug=slug, name=slug, webhook_url="", webhook_secret="")


def known_partner_slugs(settings=None) -> list[str]:
    """Default partner + any in the registry (for validation / UI)."""
    if settings is None:
        from app.config import get_settings

        settings = get_settings()
    default = (getattr(settings, "default_partner", "") or "cratis").strip().lower()
    registry = _parse_registry(getattr(settings, "partners_json", "") or "")
    return [default, *[s for s in registry if s != default]]
