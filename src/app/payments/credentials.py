from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant


async def set_credentials(
    session: AsyncSession, *, restaurant: Restaurant, provider: str, secret_key: str
) -> None:
    """Store a restaurant's own PSP credentials. Never logged, never echoed
    back in full — get_credentials_status only reports whether one is set."""
    restaurant.settings = {
        **restaurant.settings,
        "payment_provider": provider,
        "payment_secret_key": secret_key,
    }
    session.add(restaurant)
    await session.flush()


async def clear_credentials(session: AsyncSession, *, restaurant: Restaurant) -> None:
    settings = dict(restaurant.settings)
    settings.pop("payment_provider", None)
    settings.pop("payment_secret_key", None)
    restaurant.settings = settings
    session.add(restaurant)
    await session.flush()


def get_credentials_status(restaurant: Restaurant) -> dict:
    provider = restaurant.settings.get("payment_provider", "mock")
    configured = bool(restaurant.settings.get("payment_secret_key"))
    return {"provider": provider if configured else "mock", "configured": configured}


def get_restaurant_secret_key(restaurant: Restaurant) -> str | None:
    return restaurant.settings.get("payment_secret_key")
