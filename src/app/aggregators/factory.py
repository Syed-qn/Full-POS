from __future__ import annotations

from typing import Any

from app.aggregators.mock import MockAggregator
from app.aggregators.port import AggregatorPort

# All major marketplace brands + UAE noon + zomato for multi-region parity.
_SUPPORTED = frozenset(
    {
        "talabat",
        "deliveroo",
        "careem",
        "ubereats",
        "noon",
        "zomato",
    }
)

# Process-local instances (mock + live) so tests can inspect last push/status.
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


def get_aggregator_port(
    provider: str,
    *,
    restaurant_settings: dict | None = None,
    force_mock: bool = False,
    client=None,
) -> AggregatorPort:
    """Return Mock or Live HTTP adapter for ``provider``.

    Live is selected when channels.<provider>.mode == "live" and api_key is set.
    ``client`` (httpx.AsyncClient) may be injected for tests.
    """
    key = (provider or "").strip().lower()
    if key not in _SUPPORTED:
        raise ValueError(f"unsupported aggregator provider: {provider}")

    cfg = _channel_cfg(restaurant_settings, key)
    use_live = (not force_mock) and is_live_mode(restaurant_settings, key)

    # Instance cache key includes mode so flipping mock↔live works mid-process.
    cache_key = f"{key}:live" if use_live else f"{key}:mock"
    if client is not None:
        # Never cache injected clients (tests)
        if use_live:
            from app.aggregators.live import LiveHttpAggregator

            return LiveHttpAggregator(key, cfg, client=client)
        return MockAggregator(key)

    if cache_key in _INSTANCES:
        return _INSTANCES[cache_key]

    if use_live:
        from app.aggregators.live import LiveHttpAggregator

        inst: AggregatorPort = LiveHttpAggregator(key, cfg, client=client)
    else:
        inst = MockAggregator(key)
    _INSTANCES[cache_key] = inst
    return inst


def reset_aggregator_instances() -> None:
    """Test helper to clear process-local adapter state."""
    _INSTANCES.clear()
