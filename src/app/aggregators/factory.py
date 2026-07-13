from __future__ import annotations

import hashlib
from typing import Any

from app.aggregators.mock import MockAggregator
from app.aggregators.port import AggregatorPort  # noqa: TC001

# Marketplace brands. Real adapters: talabat, deliveroo, keeta, ubereats,
# careem/noon (middleware POS connector). zomato → generic LiveHttp.
_SUPPORTED = frozenset(
    {
        "talabat",
        "deliveroo",
        "careem",
        "ubereats",
        "noon",
        "zomato",
        "keeta",
    }
)

# Process-local instances keyed by provider + mode + **tenant credential fingerprint**.
# Multi-tenant SaaS: Restaurant A and Restaurant B never share a live adapter.
_INSTANCES: dict[str, AggregatorPort] = {}


def supported_providers() -> list[str]:
    return sorted(_SUPPORTED)


def _channel_cfg(restaurant_settings: dict | None, provider: str) -> dict[str, Any]:
    channels = (restaurant_settings or {}).get("channels") or {}
    cfg = channels.get(provider) if isinstance(channels, dict) else None
    return dict(cfg) if isinstance(cfg, dict) else {}


def is_live_mode(restaurant_settings: dict | None, provider: str) -> bool:
    cfg = _channel_cfg(restaurant_settings, provider)
    mode = str(cfg.get("mode") or "mock").lower()
    return mode == "live" and bool(cfg.get("api_key"))


def _tenant_fingerprint(cfg: dict[str, Any]) -> str:
    """Stable short hash of tenant secrets so cache never cross-tenant.

    Mode is not included — live vs mock is a separate cache segment. Pause/resume
    (accepting flag) must not create a new adapter instance.
    """
    raw = "|".join(
        str(cfg.get(k) or "")
        for k in (
            "api_key",
            "api_secret",
            "webhook_secret",
            "access_token",
            "store_id",
            "base_url",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def get_aggregator_port(
    provider: str,
    *,
    restaurant_settings: dict | None = None,
    force_mock: bool = False,
    client=None,
) -> AggregatorPort:
    """Return Mock or Live HTTP adapter for ``provider`` using **this restaurant's** config.

    Live is selected when channels.<provider>.mode == "live" and api_key is set.
    Cache is scoped by credential fingerprint so tenants never share adapters.
    ``client`` (httpx.AsyncClient) may be injected for tests (never cached).
    """
    key = (provider or "").strip().lower()
    if key not in _SUPPORTED:
        raise ValueError(f"unsupported aggregator provider: {provider}")

    cfg = _channel_cfg(restaurant_settings, key)
    use_live = (not force_mock) and is_live_mode(restaurant_settings, key)
    fp = _tenant_fingerprint(cfg)
    cache_key = f"{key}:{'live' if use_live else 'mock'}:{fp}"

    if client is not None:
        # Never cache injected clients (tests)
        if use_live:
            return _build_live(key, cfg, client=client)
        return MockAggregator(key, cfg)

    if cache_key in _INSTANCES:
        return _INSTANCES[cache_key]

    if use_live:
        inst: AggregatorPort = _build_live(key, cfg, client=client)
    else:
        inst = MockAggregator(key, cfg)
    _INSTANCES[cache_key] = inst
    return inst


def _build_live(key: str, cfg: dict[str, Any], *, client=None) -> AggregatorPort:
    """Prefer brand-specific real adapters; fall back to generic HTTP live shell."""
    from app.aggregators.providers import build_provider_adapter

    real = build_provider_adapter(key, cfg, client=client)
    if real is not None:
        return real
    from app.aggregators.live import LiveHttpAggregator

    return LiveHttpAggregator(key, cfg, client=client)


def reset_aggregator_instances() -> None:
    """Test helper to clear process-local adapter state."""
    _INSTANCES.clear()
