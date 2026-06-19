"""Live rider position ingestion (spec §4.4.6).

A rider's WhatsApp location message is appended to the ``rider_locations``
time-series table (the canonical store — the Rider model has no last_lat/lon
columns) and a best-effort hot copy is written to the Redis GEO key
``rider_geo:{restaurant_id}``. The dispatch engine reads the latest ping per
rider from this table when scoring pickup distance.
"""

from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.models import RiderLocation
from app.identity.models import Rider


async def update_rider_location(
    session: AsyncSession,
    *,
    rider: Rider,
    latitude: float,
    longitude: float,
    accuracy: float | None = None,
    speed: float | None = None,
    heading: float | None = None,
    ts: datetime | None = None,
) -> RiderLocation:
    """Append a rider location ping + best-effort Redis GEO hot copy. Caller commits."""
    now = ts or datetime.now(timezone.utc)
    ping = RiderLocation(
        rider_id=rider.id,
        restaurant_id=rider.restaurant_id,
        latitude=latitude,
        longitude=longitude,
        accuracy=accuracy,
        speed=speed,
        heading=heading,
        ts=now,
    )
    session.add(ping)
    _write_redis_geo(rider.restaurant_id, rider.id, latitude, longitude)
    return ping


def _write_redis_geo(
    restaurant_id: int, rider_id: int, lat: float, lon: float
) -> None:
    """Best-effort hot copy to Redis GEO. No-op if redis unavailable (tests)."""
    try:
        from app.redis_client import get_redis

        redis = get_redis()
        redis.geoadd(f"rider_geo:{restaurant_id}", (lon, lat, str(rider_id)))
    except Exception:
        pass
