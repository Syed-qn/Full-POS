from fastapi import FastAPI

from app.identity.router import router as identity_router
from app.menu.router import router as menu_router
from app.webhook.router import router as webhook_router


def create_app() -> FastAPI:
    app = FastAPI(title="Restaurant WhatsApp Platform")
    app.include_router(identity_router)
    app.include_router(menu_router)
    app.include_router(webhook_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
