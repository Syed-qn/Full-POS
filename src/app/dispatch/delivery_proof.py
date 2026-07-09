"""Delivery proof: rider-uploaded photo + OTP confirmation.

OTP is generated when an order reaches ``arriving``. When restaurant settings
``delivery.require_otp_on_deliver`` is true (snapshotted on order as
``otp_required_at_deliver``), verification **gates** the delivered transition.

Photos may be a remote URL or base64 payload stored under media/delivery_proofs/.
"""
from __future__ import annotations

import base64
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.delivery import _DELIVERY_FSM
from app.ordering.models import Order

DELIVERABLE_STATUSES = set(_DELIVERY_FSM.keys())

_PROOF_ROOT = Path("media/delivery_proofs")
_DATA_URL_RE = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$", re.I)


class DeliveryPhotoError(ValueError):
    """Raised when a delivery photo can't be attached to this order."""


class OtpVerificationError(ValueError):
    """Raised when a delivery OTP is submitted but does not match."""


class OtpRequiredError(ValueError):
    """Raised when deliver is attempted without a verified OTP and OTP is required."""


async def set_delivery_photo(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    photo_url: str | None = None,
    photo_base64: str | None = None,
) -> Order:
    """Attach proof-of-delivery photo (URL and/or base64 upload)."""
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise DeliveryPhotoError(f"order {order_id} not found")
    if order.status not in DELIVERABLE_STATUSES:
        raise DeliveryPhotoError(
            f"cannot attach a delivery photo to order {order_id} in status "
            f"{order.status!r}"
        )
    if not photo_url and not photo_base64:
        raise DeliveryPhotoError("photo_url or photo_base64 is required")

    if photo_base64:
        raw = photo_base64.strip()
        ext = "jpg"
        m = _DATA_URL_RE.match(raw)
        if m:
            ext = "png" if m.group(1).lower() == "png" else "jpg"
            raw = m.group(2)
        try:
            data = base64.b64decode(raw, validate=True)
        except Exception as exc:  # noqa: BLE001
            raise DeliveryPhotoError("invalid photo_base64") from exc
        if len(data) > 8 * 1024 * 1024:
            raise DeliveryPhotoError("photo too large (max 8MB)")
        dest_dir = _PROOF_ROOT / str(restaurant_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        fname = f"{order_id}_{secrets.token_hex(6)}.{ext}"
        path = dest_dir / fname
        path.write_bytes(data)
        order.delivery_photo_path = str(path)
        # Public-relative URL for clients that only understand URLs.
        order.delivery_photo_url = photo_url or f"/media/delivery_proofs/{restaurant_id}/{fname}"
    else:
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
    """Check a submitted OTP against the order's stored code."""
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise OtpVerificationError(f"order {order_id} not found")
    if not order.delivery_otp or order.delivery_otp != otp:
        raise OtpVerificationError("delivery OTP does not match")
    order.delivery_otp_verified_at = datetime.now(timezone.utc)
    return True


def assert_otp_satisfied(order: Order) -> None:
    """Raise if OTP is required but not verified."""
    if getattr(order, "otp_required_at_deliver", False) and not order.delivery_otp_verified_at:
        raise OtpRequiredError(
            f"order {order.id} requires OTP verification before delivery"
        )
