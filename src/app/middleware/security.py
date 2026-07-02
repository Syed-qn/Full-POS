"""Security headers middleware (P7-T6 / P7-T13).

Adds security headers to every response, including Content-Security-Policy.
HSTS is gated on the ``hsts`` constructor parameter (driven by
``APP_HSTS_ENABLED`` in config) so it is never emitted over plain HTTP in dev.
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every response."""

    def __init__(self, app, *, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        path = request.url.path
        if path.startswith("/simulator"):
            # Dev-only simulator needs inline styles + scripts + same-origin fetch
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'",
            )
        elif path.startswith(
            ("/api", "/webhooks", "/health", "/metrics", "/openapi", "/docs", "/redoc")
        ):
            # Pure API / machine endpoints: lock everything down.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'none'; frame-ancestors 'none'",
            )
        else:
            # Single-page dashboard served from this origin. Allow its own bundled
            # JS/CSS ('self'), inline styles emitted by recharts/leaflet, Google
            # Fonts, OpenStreetMap map tiles, and same-origin API calls. Without
            # this the browser blocks the SPA's own assets and renders a blank page.
            # Facebook domains are whitelisted for WhatsApp Embedded Signup: the FB
            # JS SDK script (connect.facebook.net), its hidden comms iframe + login
            # popup (*.facebook.com), and the Graph API code-exchange/session XHRs
            # (graph.facebook.com). Without these the "Connect with Facebook" popup
            # is blocked by CSP.
            response.headers.setdefault(
                "Content-Security-Policy",
                "default-src 'self'; "
                "script-src 'self' https://connect.facebook.net; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' data: https://fonts.gstatic.com; "
                "img-src 'self' data: blob: https:; "
                "connect-src 'self' https://graph.facebook.com https://www.facebook.com; "
                "frame-src https://www.facebook.com https://web.facebook.com https://staticxx.facebook.com; "
                "frame-ancestors 'none'; "
                "base-uri 'self'",
            )
        if self._hsts:
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains",
            )
        return response
