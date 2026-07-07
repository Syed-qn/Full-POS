from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.cashdrawer.router import router as cashdrawer_router
from app.cod.router import router as cod_router
from app.kds.router import router as kds_router
from app.config import get_settings
from app.conversation.router import router as conversation_router
from app.db import get_engine
from app.dispatch.rider_app_router import router as rider_app_router
from app.dispatch.router import router as dispatch_router
from app.dispatch.tracking_router import router as tracking_router
from app.identity.router import router as identity_router
from app.idempotency.middleware import IdempotencyMiddleware
from app.menu.router import router as menu_router
from app.middleware.security import SecurityHeadersMiddleware
from app.middleware.timing import ResponseTimingMiddleware
from app.ordering.customer_router import router as customer_router
from app.ordering.router import router as ordering_router
from app.webhook.router import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    redis_conn = None
    limiter_installed = False

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

    # One Redis connection shared by the rate limiter, geocode cache, and batch preview.
    if (
        settings.rate_limit_enabled
        or settings.geocode_cache_enabled
        or settings.batch_preview_cache_enabled
    ):
        redis_conn = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=3,
        )
    if settings.rate_limit_enabled and redis_conn is not None:
        from app.ratelimit.bucket import TokenBucketLimiter
        from app.ratelimit.deps import get_limiter, set_limiter

        # Tests inject an isolated limiter via ``set_limiter`` before lifespan
        # runs — never overwrite an already-installed instance.
        if get_limiter() is None:
            set_limiter(TokenBucketLimiter(redis_conn))
            limiter_installed = True
    if settings.geocode_cache_enabled and redis_conn is not None:
        from app.geo.cache import set_geocode_redis

        set_geocode_redis(redis_conn)
    if settings.batch_preview_cache_enabled and redis_conn is not None:
        from app.dispatch.preview_cache import set_preview_cache_redis

        set_preview_cache_redis(redis_conn)

    # In-process dispatch sweep: re-runs dispatch for restaurants with ready+
    # unassigned orders so held (batch-window) orders are released once they mature
    # and stuck no-rider orders keep retrying. Essential on web-only deploys (Render)
    # where no Celery beat/worker runs. Disabled in tests via APP_DISPATCH_INPROCESS_SWEEP.
    import asyncio

    sweep_task: asyncio.Task | None = None
    if settings.dispatch_inprocess_sweep:
        async def _dispatch_sweep_loop() -> None:
            from app.dispatch.service import sweep_ready_once

            interval = max(5.0, float(settings.dispatch_sweep_seconds))
            while True:
                try:
                    await asyncio.sleep(interval)
                    await sweep_ready_once()
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 — never let the loop die
                    _log.exception("in-process dispatch sweep iteration failed")

        sweep_task = asyncio.create_task(_dispatch_sweep_loop())
        _log.info("in-process dispatch sweep started (every %ss)", settings.dispatch_sweep_seconds)

    yield  # serve requests

    # --- shutdown ---
    if sweep_task is not None:
        sweep_task.cancel()
        try:
            await sweep_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass

    if limiter_installed:
        from app.ratelimit.deps import set_limiter

        set_limiter(None)
    if redis_conn is not None:
        from app.dispatch.preview_cache import set_preview_cache_redis
        from app.geo.cache import set_geocode_redis

        set_geocode_redis(None)
        set_preview_cache_redis(None)
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
    app.add_middleware(ResponseTimingMiddleware)
    # Runs innermost (closest to routing): dedupes replayed mutating requests
    # carrying an Idempotency-Key header before/after the route handler.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.hsts_enabled)
    # CORSMiddleware runs first on request (handles pre-flight) / last on response.
    if settings.cors_allow_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Idempotency-Key"],
        )

    app.include_router(identity_router)
    app.include_router(menu_router)
    app.include_router(ordering_router)
    app.include_router(customer_router)
    app.include_router(conversation_router)
    app.include_router(webhook_router)
    app.include_router(cod_router)
    app.include_router(kds_router)
    app.include_router(cashdrawer_router)
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

    # Partner integration: manager-authed key management + API-key-authed pulls.
    from app.partner.router import integration_router, keys_router, partner_router

    app.include_router(keys_router)
    app.include_router(partner_router)
    app.include_router(integration_router)

    from app.catalog.router import router as catalog_router

    app.include_router(catalog_router)

    from app.pos.router import router as pos_router

    app.include_router(pos_router)

    from app.wallet.router import router as wallet_router

    app.include_router(wallet_router)

    from app.coupons.router import router as coupons_router

    app.include_router(coupons_router)

    from app.tickets.router import router as tickets_router

    app.include_router(tickets_router)

    from app.whatsapp.template_router import router as wa_template_router

    app.include_router(wa_template_router)

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
    # the image on submit and the dashboard can preview it. Backed by Postgres
    # (marketing_media) so images survive redeploys on ephemeral-disk hosts;
    # included before the SPA catch-all so /media/* isn't shadowed.
    from app.marketing.media_router import router as media_router

    app.include_router(media_router)

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
