"""Delivery proof: rider-uploaded photo + OTP confirmation.

Both are additive/informational evidence attached to a delivery in progress —
neither is a hard gate on the ``advance_delivery`` FSM in ``delivery.py``. The
OTP is generated automatically when an order reaches ``arriving`` (see
``advance_delivery``); verifying it does not block the ``delivered``
transition, it's just recorded for ops visibility.

No real blob-storage vendor is wired into this repo yet — ``delivery_photo_url``
just stores whatever URL string the rider app hands us.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.delivery import _DELIVERY_FSM
from app.ordering.models import Order

# Orders in any of these statuses are still "in flight" to the customer — a
# rider proof photo may be attached any time from rider-assignment up to (but
# not including) delivered. Sourced from the FSM's own transition table so
# this can never drift from the real delivery states.
DELIVERABLE_STATUSES = set(_DELIVERY_FSM.keys())


class DeliveryPhotoError(ValueError):
    """Raised when a delivery photo can't be attached to this order."""


class OtpVerificationError(ValueError):
    """Raised when a delivery OTP is submitted but does not match."""


async def set_delivery_photo(
    session: AsyncSession, *, restaurant_id: int, order_id: int, photo_url: str
) -> Order:
    """Attach a rider-uploaded proof-of-delivery photo URL to an in-flight order."""
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise DeliveryPhotoError(f"order {order_id} not found")
    if order.status not in DELIVERABLE_STATUSES:
        raise DeliveryPhotoError(
            f"cannot attach a delivery photo to order {order_id} in status "
            f"{order.status!r}"
        )
    order.delivery_photo_url = photo_url
    return order


async def generate_delivery_otp(session: AsyncSession, *, order: Order) -> str:
    """Generate and store a fresh 4-digit delivery confirmation code."""
    otp = f"{secrets.randbelow(10000):04d}"
    order.delivery_otp = otp
    order.delivery_otp_verified_at = None
    return otp


async def verify_delivery_otp(
    session: AsyncSession, *, restaurant_id: int, order_id: int, otp: str
) -> bool:
    """Check a submitted OTP against the order's stored code.

    Informational only — never gates the delivery FSM. Raises
    ``OtpVerificationError`` (with a clear message) on a missing order, a
    tenant mismatch, or a non-matching code.
    """
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise OtpVerificationError(f"order {order_id} not found")
    if not order.delivery_otp or order.delivery_otp != otp:
        raise OtpVerificationError("delivery OTP does not match")
    order.delivery_otp_verified_at = datetime.now(timezone.utc)
    return True
