"""Late-delivery apology coupon service (spec §4.5).

``issue_coupon`` mints a single-use coupon with a unique code, a 30-day default
expiry, ``status="issued"``, linked to the order/customer that caused it.
``redeem_coupon`` validates the code is issued + unredeemed + unexpired and marks
it ``redeemed`` with the redeeming order. Every mint/redeem is audited in the
caller's transaction (caller commits).
"""

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.coupons.models import Coupon

DEFAULT_VALIDITY_DAYS = 30


class CouponError(ValueError):
    """Raised on invalid issue/redeem (unknown, expired, already redeemed)."""


def _generate_code(restaurant_id: int) -> str:
    return f"SORRY-{restaurant_id}-{secrets.token_hex(3).upper()}"


async def issue_coupon(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    order_id: int,
    discount_aed: Decimal,
    validity_days: int = DEFAULT_VALIDITY_DAYS,
) -> Coupon:
    """Mint a single-use apology coupon with a unique code. Caller commits."""
    code = _generate_code(restaurant_id)
    while (
        await session.scalar(select(Coupon).where(Coupon.code == code)) is not None
    ):
        code = _generate_code(restaurant_id)
    coupon = Coupon(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_id=order_id,
        code=code,
        discount_aed=discount_aed,
        status="issued",
        expires_at=datetime.now(timezone.utc) + timedelta(days=validity_days),
    )
    session.add(coupon)
    await session.flush()
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="coupon",
        entity_id=str(coupon.id),
        action="issued",
        before=None,
        after={"code": code, "discount_aed": str(discount_aed)},
    )
    return coupon


async def redeem_coupon(
    session: AsyncSession, *, restaurant_id: int, code: str, order_id: int
) -> Coupon:
    """Validate + redeem a coupon. Raises CouponError on unknown/expired/already-redeemed."""
    coupon = await session.scalar(
        select(Coupon).where(
            Coupon.restaurant_id == restaurant_id, Coupon.code == code
        )
    )
    if coupon is None:
        raise CouponError(f"unknown coupon {code}")
    if coupon.status != "issued":
        raise CouponError(f"coupon {code} is {coupon.status}, not redeemable")
    now = datetime.now(timezone.utc)
    if coupon.expires_at is not None and coupon.expires_at < now:
        coupon.status = "expired"
        raise CouponError(f"coupon {code} expired")
    coupon.status = "redeemed"
    coupon.redeemed_at = now
    coupon.redeemed_on_order_id = order_id
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="coupon",
        entity_id=str(coupon.id),
        action="redeemed",
        before={"status": "issued"},
        after={"status": "redeemed", "order_id": order_id},
    )
    return coupon
