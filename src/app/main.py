from fastapi import FastAPI

from app.cod.router import router as cod_router
from app.config import get_settings
from app.dispatch.router import router as dispatch_router
from app.identity.router import router as identity_router
from app.menu.router import router as menu_router
from app.ordering.router import router as ordering_router
from app.webhook.router import router as webhook_router


def create_app() -> FastAPI:
    app = FastAPI(title="Restaurant WhatsApp Platform")
    app.include_router(identity_router)
    app.include_router(menu_router)
    app.include_router(ordering_router)
    app.include_router(webhook_router)
    app.include_router(cod_router)
    app.include_router(dispatch_router)

    settings = get_settings()
    if settings.whatsapp_provider == "mock":
        from apps.simulator.router import router as simulator_router
        app.include_router(simulator_router)

    # Predictions router (P6-T8) — registered when available
    try:
        from app.predictions.router import router as predictions_router
        app.include_router(predictions_router)
    except ImportError:
        pass

    # Marketing router (P6-T16) — registered when available
    try:
        from app.marketing.router import router as marketing_router
        app.include_router(marketing_router)
    except ImportError:
        pass

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
