"""Native rider app (Android): pairing + device auth + background GPS ingest.

Flow:
  1. Manager (or onboarding) generates a one-time *pairing code* for a rider and
     it's sent to them over WhatsApp (``send_rider_app_pairing``).
  2. The rider installs the APK, enters the code once — ``redeem_pairing_code``
     swaps it for a long-lived ``device_token`` the app stores.
  3. The app streams background GPS to ``record_rider_app_location`` using that
     token; each fix updates the rider's active order tracking session(s), writes
     a RiderLocation, and (on the first ping of an order) reveals the rider's stop
     and notifies the customer — the same gate the web tracker used.

The location ingest is deliberately rider-scoped (not per-order): one persistent
stream maps to whatever order the rider is currently delivering, so the rider
never re-pairs or re-opens anything per delivery.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.tracking_live import (
    TRACKING_ACTIVE,
    _validate_coordinates,
)
from app.dispatch.models import OrderTrackingSession, RiderLocation
from app.identity.models import Rider

_PAIRING_TTL_MINUTES = 60
_PAIRING_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no ambiguous chars (0/O/1/I)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_pairing_code() -> str:
    return "".join(secrets.choice(_PAIRING_ALPHABET) for _ in range(6))


def _new_device_token() -> str:
    return secrets.token_urlsafe(32)


async def create_pairing_code(session: AsyncSession, *, rider: Rider) -> str:
    """Generate (and store) a fresh one-time pairing code for the rider."""
    rider.pairing_code = _new_pairing_code()
    rider.pairing_code_expires_at = _now() + timedelta(minutes=_PAIRING_TTL_MINUTES)
    await session.flush()
    return rider.pairing_code


async def send_rider_app_pairing(session: AsyncSession, *, rider: Rider) -> str:
    """Generate a pairing code and send it (with the APK link) to the rider over
    WhatsApp. Caller commits + flushes the outbox. Returns the code."""
    from app.config import get_settings
    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    code = await create_pairing_code(session, rider=rider)
    apk_url = get_settings().rider_app_apk_url
    lines = [
        "📱 *Rider app — pairing*",
        "",
        f"Your one-time code: *{code}*  (valid {_PAIRING_TTL_MINUTES} min)",
    ]
    if apk_url:
        lines += ["", f"1) Install the app: {apk_url}", "2) Open it and enter the code above."]
    else:
        lines += ["", "Open the rider app and enter the code above to pair."]
    await enqueue_message(
        session,
        restaurant_id=rider.restaurant_id,
        to_phone=rider.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": "\n".join(lines)},
        idempotency_key=f"app-pair-{rider.id}-{code}",
    )
    return code


async def redeem_pairing_code(session: AsyncSession, *, code: str) -> Rider | None:
    """Swap a valid, unexpired pairing code for a long-lived device token.

    Returns the paired Rider (with ``device_token`` set) or None if the code is
    unknown/expired. Single-use: the code is cleared on success."""
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    rider = await session.scalar(
        select(Rider).where(Rider.pairing_code == normalized)
    )
    if rider is None or rider.pairing_code_expires_at is None:
        return None
    if rider.pairing_code_expires_at <= _now():
        return None
    rider.device_token = _new_device_token()
    rider.pairing_code = None
    rider.pairing_code_expires_at = None
    await session.flush()
    return rider


async def get_rider_by_device_token(
    session: AsyncSession, *, token: str
) -> Rider | None:
    if not token:
        return None
    return await session.scalar(select(Rider).where(Rider.device_token == token))


async def set_push_token(session: AsyncSession, *, rider: Rider, push_token: str) -> None:
    """Store the rider's Expo push token (set by the app after it registers for
    notifications). Caller commits."""
    rider.push_token = (push_token or "").strip() or None
    await session.flush()


async def notify_rider_assigned(
    session: AsyncSession, *, rider: Rider, order_count: int
) -> bool:
    """Push the rider that a delivery was assigned, so they open the app (which
    then streams GPS + shows the run). Best-effort: a paired rider with no push
    token, or a push failure, returns False and never raises. Returns True if a
    push was sent."""
    if not rider.push_token:
        return False
    from app.notifications.factory import get_push_provider
    from app.notifications.port import PushMessage

    provider = get_push_provider()
    plural = "deliveries" if order_count != 1 else "delivery"
    return await provider.send(
        PushMessage(
            to_token=rider.push_token,
            title="New delivery assigned",
            body=f"You have {order_count} {plural} ready — open the app to start.",
            data={"type": "assignment"},
        )
    )


async def record_rider_app_location(
    session: AsyncSession,
    *,
    rider: Rider,
    latitude: float,
    longitude: float,
    accuracy: float | None = None,
    speed: float | None = None,
    heading: float | None = None,
) -> list[int]:
    """Apply one background GPS fix to ALL the rider's active tracking sessions
    and write a single RiderLocation. Returns the order ids whose session got its
    FIRST ping (so the caller can reveal that stop + notify the customer)."""
    _validate_coordinates(latitude, longitude)
    now = _now()
    # Atomically CLAIM the first ping per order: stamp last_location_at only on
    # sessions that have never received one. The conditional UPDATE ... WHERE
    # last_location_at IS NULL ... RETURNING guarantees exactly ONE concurrent
    # ping wins per order, so the customer's "on the way" notification fires once
    # even though the app pings from two sources at once (foreground poll +
    # background GPS stream). The old read-then-write let both pings see NULL and
    # each notify, double-messaging the customer.
    first_ping_order_ids: list[int] = list(
        (
            await session.execute(
                sa_update(OrderTrackingSession)
                .where(
                    OrderTrackingSession.rider_id == rider.id,
                    OrderTrackingSession.status == TRACKING_ACTIVE,
                    OrderTrackingSession.last_location_at.is_(None),
                )
                .values(last_location_at=now)
                .returning(OrderTrackingSession.order_id)
                .execution_options(synchronize_session=False)
            )
        )
        .scalars()
        .all()
    )
    sessions = (
        await session.scalars(
            select(OrderTrackingSession).where(
                OrderTrackingSession.rider_id == rider.id,
                OrderTrackingSession.status == TRACKING_ACTIVE,
            )
        )
    ).all()
    for s in sessions:
        s.latest_latitude = latitude
        s.latest_longitude = longitude
        s.latest_accuracy = accuracy
        s.latest_speed = speed
        s.latest_heading = heading
        s.last_location_at = now
        if s.expires_at <= now:
            s.expires_at = now + timedelta(hours=6)
    session.add(
        RiderLocation(
            rider_id=rider.id,
            restaurant_id=rider.restaurant_id,
            latitude=latitude,
            longitude=longitude,
            accuracy=accuracy,
            speed=speed,
            heading=heading,
            ts=now,
        )
    )
    try:
        from app.dispatch.rider_location import _write_redis_geo

        _write_redis_geo(rider.restaurant_id, rider.id, latitude, longitude)
    except Exception:
        pass
    return first_ping_order_ids
