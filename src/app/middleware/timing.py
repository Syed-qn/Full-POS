"""API response timing — surfaces slow dashboard paths on Render."""
from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("app.timing")

_SLOW_MS = 400.0


class ResponseTimingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        response.headers["X-Response-Time-Ms"] = f"{elapsed_ms:.1f}"
        if elapsed_ms > _SLOW_MS and request.url.path.startswith("/api/"):
            logger.warning(
                "slow_api path=%s method=%s ms=%.1f",
                request.url.path,
                request.method,
                elapsed_ms,
            )
        return response