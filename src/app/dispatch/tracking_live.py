from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.dispatch.models import OrderTrackingSession, RiderLocation
from app.ordering.models import Order


TRACKING_ACTIVE = "active"
TRACKING_STOPPED = "stopped"
TRACKING_EXPIRED = "expired"


@dataclass
class TrackingAccess:
    session: OrderTrackingSession
    order: Order


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_token() -> str:
    return token_urlsafe(18)


def build_tracking_url(tracking_token: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/track/{tracking_token}"


def build_rider_tracking_url(rider_token: str) -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/rider-track/{rider_token}"


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if not (-90 <= latitude <= 90):
        raise ValueError("latitude must be between -90 and 90")
    if not (-180 <= longitude <= 180):
        raise ValueError("longitude must be between -180 and 180")


async def ensure_tracking_session(
    session: AsyncSession, *, order: Order
) -> OrderTrackingSession:
    if order.rider_id is None:
        raise ValueError("order has no assigned rider")
    existing = await session.scalar(
        select(OrderTrackingSession).where(OrderTrackingSession.order_id == order.id)
    )
    now = _now()
    if existing is not None:
        existing.rider_id = order.rider_id
        existing.restaurant_id = order.restaurant_id
        if existing.status != TRACKING_ACTIVE:
            existing.status = TRACKING_ACTIVE
            existing.started_at = now
            existing.stopped_at = None
        if existing.expires_at <= now:
            existing.expires_at = now + timedelta(hours=6)
        if not existing.tracking_token:
            existing.tracking_token = _new_token()
        if not existing.rider_token:
            existing.rider_token = _new_token()
        return existing

    created = OrderTrackingSession(
        order_id=order.id,
        rider_id=order.rider_id,
        restaurant_id=order.restaurant_id,
        tracking_token=_new_token(),
        rider_token=_new_token(),
        status=TRACKING_ACTIVE,
        started_at=now,
        expires_at=now + timedelta(hours=6),
    )
    session.add(created)
    await session.flush()
    return created


async def stop_tracking_session(
    session: AsyncSession, *, order_id: int, reason: str = TRACKING_STOPPED
) -> OrderTrackingSession | None:
    tracking = await session.scalar(
        select(OrderTrackingSession).where(OrderTrackingSession.order_id == order_id)
    )
    if tracking is None:
        return None
    now = _now()
    tracking.status = reason
    tracking.stopped_at = now
    tracking.expires_at = now
    return tracking


async def get_tracking_session_for_order(
    session: AsyncSession, *, order_id: int, restaurant_id: int
) -> TrackingAccess | None:
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        return None
    tracking = await session.scalar(
        select(OrderTrackingSession).where(OrderTrackingSession.order_id == order_id)
    )
    if tracking is None:
        return None
    return TrackingAccess(session=tracking, order=order)


async def get_tracking_session_by_public_token(
    session: AsyncSession, *, tracking_token: str
) -> TrackingAccess | None:
    tracking = await session.scalar(
        select(OrderTrackingSession).where(
            OrderTrackingSession.tracking_token == tracking_token
        )
    )
    if tracking is None:
        return None
    order = await session.get(Order, tracking.order_id)
    if order is None:
        return None
    return TrackingAccess(session=tracking, order=order)


async def get_tracking_session_by_rider_token(
    session: AsyncSession, *, rider_token: str
) -> TrackingAccess | None:
    tracking = await session.scalar(
        select(OrderTrackingSession).where(OrderTrackingSession.rider_token == rider_token)
    )
    if tracking is None:
        return None
    order = await session.get(Order, tracking.order_id)
    if order is None:
        return None
    return TrackingAccess(session=tracking, order=order)


def is_tracking_accessible(tracking: OrderTrackingSession) -> bool:
    now = _now()
    return tracking.status == TRACKING_ACTIVE and tracking.expires_at > now


async def record_tracking_location(
    session: AsyncSession,
    *,
    tracking: OrderTrackingSession,
    latitude: float,
    longitude: float,
    accuracy: float | None = None,
    speed: float | None = None,
    heading: float | None = None,
) -> RiderLocation:
    _validate_coordinates(latitude, longitude)
    now = _now()
    tracking.latest_latitude = latitude
    tracking.latest_longitude = longitude
    tracking.latest_accuracy = accuracy
    tracking.latest_speed = speed
    tracking.latest_heading = heading
    tracking.last_location_at = now
    tracking.status = TRACKING_ACTIVE
    if tracking.expires_at <= now:
        tracking.expires_at = now + timedelta(hours=6)

    ping = RiderLocation(
        rider_id=tracking.rider_id,
        restaurant_id=tracking.restaurant_id,
        latitude=latitude,
        longitude=longitude,
        accuracy=accuracy,
        speed=speed,
        heading=heading,
        ts=now,
    )
    session.add(ping)
    try:
        from app.dispatch.rider_location import _write_redis_geo

        _write_redis_geo(tracking.restaurant_id, tracking.rider_id, latitude, longitude)
    except Exception:
        pass
    return ping
