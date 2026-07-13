"""Marketplace-specific aggregator adapters (real partner API shapes).

Supported real adapters (order accept path aligned to public docs):
- talabat   — Delivery Hero POS Middleware (integration.talabat.com)
- deliveroo — Deliveroo Order API (api-docs.deliveroo.com)
- keeta     — Keeta Open API (api-docs.mykeeta.com)
- ubereats  — Uber Eats Order Manager (developer.uber.com/docs/eats)
- careem    — Middleware POS connector (no public native Careem API)
- noon      — Middleware POS connector (no public native Noon Food API)

Zomato still uses the generic LiveHttpAggregator until mapped.
"""

from __future__ import annotations

from typing import Any

from app.aggregators.port import AggregatorPort


def build_provider_adapter(
    provider: str,
    config: dict[str, Any] | None = None,
    *,
    client=None,
) -> AggregatorPort | None:
    """Return a real partner adapter if one is registered; else None."""
    key = (provider or "").strip().lower()
    cfg = dict(config or {})

    if key == "talabat":
        from app.aggregators.providers.talabat import TalabatAdapter

        return TalabatAdapter(cfg, client=client)
    if key == "deliveroo":
        from app.aggregators.providers.deliveroo import DeliverooAdapter

        return DeliverooAdapter(cfg, client=client)
    if key in ("keeta", "mykeeta"):
        from app.aggregators.providers.keeta import KeetaAdapter

        return KeetaAdapter(cfg, client=client)
    if key in ("ubereats", "uber_eats", "uber"):
        from app.aggregators.providers.ubereats import UberEatsAdapter

        return UberEatsAdapter(cfg, client=client)
    if key in ("careem", "noon"):
        from app.aggregators.providers.middleware import MiddlewareChannelAdapter

        return MiddlewareChannelAdapter(key, cfg, client=client)
    return None


def registered_real_providers() -> list[str]:
    return ["careem", "deliveroo", "keeta", "noon", "talabat", "ubereats"]
