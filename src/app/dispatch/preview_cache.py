"""Tenant-scoped TTL cache for ``preview_batch_groups`` results.

Batch preview runs the dispatch dry planner (OR-Tools / geo) and is far too slow
for a 400 ms dashboard budget on Render. Results are keyed per restaurant so
multi-tenant isolation is preserved. Redis when available; in-process fallback
for web-only deploys without Redis.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_KEY_PREFIX = "batch_preview:"
_redis_client: Any = None
# In-process fallback: restaurant_id -> (expires_monotonic, payload)
_memory: dict[int, tuple[float, dict[int, str]]] = {}


def set_preview_cache_redis(client: Any) -> None:
    global _redis_client
    _redis_client = client


def _ttl_seconds() -> int:
    return get_settings().batch_preview_cache_ttl_seconds


def _redis_key(restaurant_id: int) -> str:
    return f"{_KEY_PREFIX}{restaurant_id}"


async def get_cached_preview(restaurant_id: int) -> dict[int, str] | None:
    r = _redis_client
    if r is not None:
        try:
            hit = await r.get(_redis_key(restaurant_id))
            if hit:
                raw = json.loads(hit)
                return {int(k): v for k, v in raw.items()}
        except Exception as exc:  # noqa: BLE001
            logger.debug("batch preview cache read failed (%s)", exc)

    entry = _memory.get(restaurant_id)
    if entry is not None:
        expires, payload = entry
        if time.monotonic() < expires:
            return payload
        _memory.pop(restaurant_id, None)
    return None


async def set_cached_preview(restaurant_id: int, preview: dict[int, str]) -> None:
    ttl = _ttl_seconds()
    serializable = {str(k): v for k, v in preview.items()}
    r = _redis_client
    if r is not None:
        try:
            await r.set(_redis_key(restaurant_id), json.dumps(serializable), ex=ttl)
        except Exception as exc:  # noqa: BLE001
            logger.debug("batch preview cache write failed (%s)", exc)

    _memory[restaurant_id] = (time.monotonic() + ttl, dict(preview))


async def invalidate_preview_cache(restaurant_id: int) -> None:
    """Drop cached labels when dispatch pool changes (assign, ready, cancel)."""
    r = _redis_client
    if r is not None:
        try:
            await r.delete(_redis_key(restaurant_id))
        except Exception as exc:  # noqa: BLE001
            logger.debug("batch preview cache invalidate failed (%s)", exc)
    _memory.pop(restaurant_id, None)