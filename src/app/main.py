from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.cod.router import router as cod_router
from app.config import get_settings
from app.conversation.router import router as conversation_router
from app.db import get_engine
from app.dispatch.rider_app_router import router as rider_app_router
from app.dispatch.router import router as dispatch_router
from app.dispatch.tracking_router import router as tracking_router
from app.identity.router import router as identity_router
from app.menu.router import router as menu_router
from app.middleware.security import SecurityHeadersMiddleware
from app.ordering.customer_router import router as customer_router
from app.ordering.router import router as ordering_router
from app.webhook.router import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    redis_conn = None

    # --- startup ---
    from app.obs.sentry import init_sentry
    init_sentry(settings.sentry_dsn, environment=settings.env)

    # Surface the active geo provider on boot so a misconfigured production
    # (defaulting to the offline straight-line fallback instead of Google road
    # distance) is obvious in the logs rather than silently mis-pricing delivery.
    import logging

    _log = logging.getLogger("app.geo")
    if settings.geo_provider == "google_maps" and settings.google_maps_api_key.get_secret_value():
        _log.info("geo provider: google_maps (real road distance)")
    else:
        _log.warning(
            "geo provider: %s WITHOUT a Google key — delivery distances are "
            "STRAIGHT-LINE estimates, not road distance. Set APP_GEO_PROVIDER="
            "google_maps + APP_GOOGLE_MAPS_API_KEY to fix.",
            settings.geo_provider,
        )

    # One Redis connection shared by the rate limiter and the geocode cache.
    if settings.rate_limit_enabled or settings.geocode_cache_enabled:
        redis_conn = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=3,
        )
    if settings.rate_limit_enabled and redis_conn is not None:
        from app.ratelimit.bucket import TokenBucketLimiter
        from app.ratelimit.deps import set_limiter

        set_limiter(TokenBucketLimiter(redis_conn))
    if settings.geocode_cache_enabled and redis_conn is not None:
        from app.geo.cache import set_geocode_redis

        set_geocode_redis(redis_conn)

    yield  # serve requests

    # --- shutdown ---
    if redis_conn is not None:
        from app.geo.cache import set_geocode_redis

        set_geocode_redis(None)
        await redis_conn.aclose()

    engine = get_engine()
    if engine is not None:
        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Restaurant WhatsApp Platform", lifespan=lifespan)

    # Middleware order matters: add_middleware inserts at the front of the stack,
    # so the last call here executes FIRST on the request path.
    # SecurityHeadersMiddleware runs last on request / first on response.
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.hsts_enabled)
    # CORSMiddleware runs first on request (handles pre-flight) / last on response.
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        )

    app.include_router(identity_router)
    app.include_router(menu_router)
    app.include_router(ordering_router)
    app.include_router(customer_router)
    app.include_router(conversation_router)
    app.include_router(webhook_router)
    app.include_router(cod_router)
    app.include_router(dispatch_router)
    app.include_router(tracking_router)
    app.include_router(rider_app_router)

    if settings.whatsapp_provider == "mock":
        from apps.simulator.router import router as simulator_router

        app.include_router(simulator_router)

    # P6 modules — fully implemented (predictions + marketing routers, workers, services, ports, tests)
    from app.predictions.router import router as predictions_router
    from app.marketing.router import router as marketing_router

    app.include_router(predictions_router)
    app.include_router(marketing_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/version")
    async def version() -> dict:
        # Render injects RENDER_GIT_COMMIT at build/runtime; lets us confirm
        # exactly which commit is live instead of inferring it from behaviour.
        import os

        sha = (
            os.getenv("RENDER_GIT_COMMIT")
            or os.getenv("GIT_COMMIT")
            or "unknown"
        )
        return {"commit": sha, "short": sha[:7] if sha != "unknown" else sha}

    from app.metrics import metrics_response

    @app.get("/metrics")
    async def metrics() -> Response:
        body, content_type = metrics_response()
        return Response(content=body, media_type=content_type)

    # Serve uploaded media (marketing template header images) so Meta can fetch
    # the image on submit and the dashboard can preview it. Mounted before the SPA
    # catch-all so /media/* isn't shadowed.
    media_dir = Path(settings.upload_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=str(media_dir)), name="media")

    # Serve the built React dashboard (single-service deploy): the Docker build
    # drops the compiled SPA at /app/static. Absent in local dev — there you run
    # the vite dev server. Mounted LAST so it never shadows the API/health/metrics
    # routes above; the catch-all returns index.html so client-side routes
    # (/login, /orders, …) resolve to the SPA.
    static_dir = Path(__file__).resolve().parents[2] / "static"
    if (static_dir / "index.html").is_file():
        app.mount(
            "/assets", StaticFiles(directory=static_dir / "assets"), name="assets"
        )

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> Response:
            candidate = static_dir / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


app = create_app()
