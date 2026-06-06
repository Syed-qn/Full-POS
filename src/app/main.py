from fastapi import FastAPI

from app.identity.router import router as identity_router


def create_app() -> FastAPI:
    app = FastAPI(title="Restaurant WhatsApp Platform")
    app.include_router(identity_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
