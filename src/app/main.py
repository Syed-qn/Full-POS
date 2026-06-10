from contextlib import asynccontextmanager
from typing import AsyncIterator

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.cod.router import router as cod_router
from app.config import get_settings
from app.db import get_engine
from app.dispatch.router import router as dispatch_router
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

    if settings.rate_limit_enabled:
        from app.ratelimit.bucket import TokenBucketLimiter
        from app.ratelimit.deps import set_limiter

        redis_conn = await aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_timeout=3,
        )
        set_limiter(TokenBucketLimiter(redis_conn))

    yield  # serve requests

    # --- shutdown ---
    if redis_conn is not None:
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
    app.include_router(webhook_router)
    app.include_router(cod_router)
    app.include_router(dispatch_router)

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

    from app.metrics import metrics_response

    @app.get("/metrics")
    async def metrics() -> Response:
        body, content_type = metrics_response()
        return Response(content=body, media_type=content_type)

    return app


app = create_app()
