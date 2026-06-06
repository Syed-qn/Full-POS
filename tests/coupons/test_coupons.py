"""Coupon service tests (spec §4.5): issue (unique code, 30d expiry) + single-use redeem."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.coupons.service import CouponError, issue_coupon, redeem_coupon
from app.identity.models import Restaurant
from app.ordering.models import Customer, Order


async def _seed(db_session):
    r = Restaurant(name="R", phone="+9718889999", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    c = Customer(
        restaurant_id=r.id,
        phone="+971501112222",
        name="C",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    o = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number="O1",
        status="delivered",
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("40.00"),
        total=Decimal("40.00"),
    )
    db_session.add(o)
    await db_session.commit()
    return r, c, o


async def test_issue_coupon_creates_unique_code(db_session):
    r, c, o = await _seed(db_session)
    coupon = await issue_coupon(
        db_session, restaurant_id=r.id, customer_id=c.id, order_id=o.id, discount_aed=Decimal("10.00")
    )
    await db_session.commit()
    assert coupon.code
    assert coupon.status == "issued"
    assert coupon.discount_aed == Decimal("10.00")
    assert coupon.expires_at > datetime.now(timezone.utc)


async def test_redeem_coupon_marks_redeemed(db_session):
    r, c, o = await _seed(db_session)
    coupon = await issue_coupon(
        db_session, restaurant_id=r.id, customer_id=c.id, order_id=o.id, discount_aed=Decimal("5.00")
    )
    await db_session.commit()
    redeemed = await redeem_coupon(
        db_session, restaurant_id=r.id, code=coupon.code, order_id=o.id
    )
    await db_session.commit()
    assert redeemed.status == "redeemed"
    assert redeemed.redeemed_at is not None
    assert redeemed.redeemed_on_order_id == o.id


async def test_redeem_twice_rejected(db_session):
    r, c, o = await _seed(db_session)
    coupon = await issue_coupon(
        db_session, restaurant_id=r.id, customer_id=c.id, order_id=o.id, discount_aed=Decimal("5.00")
    )
    await db_session.commit()
    await redeem_coupon(db_session, restaurant_id=r.id, code=coupon.code, order_id=o.id)
    await db_session.commit()
    with pytest.raises(CouponError):
        await redeem_coupon(db_session, restaurant_id=r.id, code=coupon.code, order_id=o.id)


async def test_redeem_expired_rejected(db_session):
    r, c, o = await _seed(db_session)
    coupon = await issue_coupon(
        db_session, restaurant_id=r.id, customer_id=c.id, order_id=o.id, discount_aed=Decimal("5.00")
    )
    coupon.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db_session.commit()
    with pytest.raises(CouponError):
        await redeem_coupon(db_session, restaurant_id=r.id, code=coupon.code, order_id=o.id)


async def test_redeem_unknown_code_rejected(db_session):
    r, c, o = await _seed(db_session)
    with pytest.raises(CouponError):
        await redeem_coupon(db_session, restaurant_id=r.id, code="NOPE", order_id=o.id)
