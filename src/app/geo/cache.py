"""Redis read-through cache for geocoding results (address → lat/lng).

Repeated addresses skip the paid, slower Geocoding API call — "repeated users
become instant" (design STEP 8). The Redis client is injected at startup via
``set_geocode_redis`` (mirroring the rate limiter). When unset (e.g. unit tests)
or on ANY Redis error, it degrades to calling the provider directly, so a Redis
outage never blocks ordering.

Only POSITIVE results are cached (a real coordinate). Misses are not cached so a
transient geocoder failure or a since-fixed typo isn't remembered forever.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re

from app.config import get_settings
from app.geo.factory import get_geo_provider

logger = logging.getLogger(__name__)

_KEY_PREFIX = "geocode:"
_redis_client = None  # set at app startup; None ⇒ cache disabled (direct call)


def set_geocode_redis(client) -> None:
    """Inject the async Redis client used for the geocode cache (or None)."""
    global _redis_client
    _redis_client = client


def _key(address: str) -> str:
    return _KEY_PREFIX + re.sub(r"\s+", " ", address.strip().lower())


async def geocode_cached(address: str) -> tuple[float, float] | None:
    """Geocode ``address`` via a Redis read-through cache.

    Returns ``(lat, lng)`` or None. The provider call runs in a worker thread
    (its httpx client is sync) so it never blocks the event loop.
    """
    if not address:
        return None
    key = _key(address)
    r = _redis_client

    if r is not None:
        try:
            hit = await r.get(key)
            if hit:
                lat, lng = json.loads(hit)
                return (float(lat), float(lng))
        except Exception as exc:  # noqa: BLE001 - cache is best-effort
            logger.debug("geocode cache read failed (%s); calling provider", exc)

    coords = await asyncio.to_thread(get_geo_provider().geocode, address)

    if coords is not None and r is not None:
        try:
            ttl = get_settings().geocode_cache_ttl_seconds
            await r.set(key, json.dumps([coords[0], coords[1]]), ex=ttl)
        except Exception as exc:  # noqa: BLE001 - cache is best-effort
            logger.debug("geocode cache write failed: %s", exc)
    return coords
