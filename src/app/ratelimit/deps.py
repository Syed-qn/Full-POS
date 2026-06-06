# src/app/ratelimit/deps.py
"""FastAPI rate-limit dependencies backed by the redis token bucket.

The active limiter is injected at app startup (and in tests) via ``set_limiter``;
when unset or ``rate_limit_enabled`` is False, the deps are no-ops so unit tests
that don't exercise rate limiting stay green.
"""
import json

from fastapi import HTTPException, Request

from app.config import get_settings
from app.ratelimit.bucket import TokenBucketLimiter

_UNIT_SECONDS = {"second": 1, "minute": 60, "hour": 3600}
_limiter: TokenBucketLimiter | None = None


def _parse(spec: str) -> tuple[int, float]:
    count, _, unit = spec.partition("/")
    secs = _UNIT_SECONDS[unit.strip().rstrip("s")]
    cap = int(count)
    return cap, cap / secs  # refill back to full over the window


def set_limiter(limiter: TokenBucketLimiter | None) -> None:
    global _limiter
    _limiter = limiter


def get_limiter() -> TokenBucketLimiter | None:
    return _limiter


async def _enforce(key: str, spec: str) -> None:
    settings = get_settings()
    if not settings.rate_limit_enabled or _limiter is None:
        return
    cap, refill = _parse(spec)
    ok, retry = await _limiter.allow(key, capacity=cap, refill_per_sec=refill)
    if not ok:
        raise HTTPException(
            429, "rate limit exceeded", headers={"Retry-After": str(retry)}
        )


async def _login_phone(request: Request) -> str:
    """Best-effort phone extraction from the login JSON body.

    Reads + caches the raw body on the request so the route handler can still
    parse it (Starlette caches ``await request.body()``).
    """
    try:
        raw = await request.body()
        if not raw:
            return ""
        return str(json.loads(raw).get("phone", ""))
    except (json.JSONDecodeError, ValueError):
        return ""


async def rate_limit_auth(request: Request) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    phone = await _login_phone(request)
    await _enforce(f"auth:{ip}:{phone}", settings.auth_rate_limit)


async def rate_limit_webhook(request: Request) -> None:
    settings = get_settings()
    ip = request.client.host if request.client else "unknown"
    await _enforce(f"webhook:{ip}", settings.webhook_rate_limit)
