from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.coupons import service as c
from app.coupons.service import CouponError


async def _coupon(db_session, rid, **kw):
    defaults = dict(
        restaurant_id=rid, discount_type="fixed", discount_value=Decimal("10.00"),
        kind="multi_use", created_by="mgr:1",
    )
    defaults.update(kw)
    return await c.create_coupon(db_session, **defaults)


async def test_fixed_redeem_applies_discount(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid)
    r = await c.validate_and_redeem(
        db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
        order_subtotal_aed=Decimal("50.00"), idempotency_key="r1",
    )
    assert r.discount_applied_aed == Decimal("10.00")


async def test_percent_redeem_capped(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid, discount_type="percent",
                       discount_value=Decimal("50.00"), max_discount_aed=Decimal("15.00"))
    r = await c.validate_and_redeem(
        db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
        order_subtotal_aed=Decimal("100.00"), idempotency_key="r1",
    )
    assert r.discount_applied_aed == Decimal("15.00")  # 50% of 100 = 50, capped at 15


async def test_below_min_order_rejected(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid, min_order_aed=Decimal("40.00"))
    with pytest.raises(CouponError):
        await c.validate_and_redeem(
            db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
            order_subtotal_aed=Decimal("30.00"), idempotency_key="r1",
        )


async def test_expired_rejected(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid,
                       expires_at=datetime.now(timezone.utc) - timedelta(days=1))
    with pytest.raises(CouponError):
        await c.validate_and_redeem(
            db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
            order_subtotal_aed=Decimal("50.00"), idempotency_key="r1",
        )


async def test_not_yet_valid_rejected(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid,
                       valid_from=datetime.now(timezone.utc) + timedelta(days=1))
    with pytest.raises(CouponError):
        await c.validate_and_redeem(
            db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
            order_subtotal_aed=Decimal("50.00"), idempotency_key="r1",
        )


async def test_single_use_second_redeem_rejected(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid, kind="single_use")
    await c.validate_and_redeem(
        db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
        order_subtotal_aed=Decimal("50.00"), idempotency_key="r1",
    )
    with pytest.raises(CouponError):
        await c.validate_and_redeem(
            db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=2,
            order_subtotal_aed=Decimal("50.00"), idempotency_key="r2",
        )


async def test_per_customer_limit(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid, per_customer_limit=1)
    await c.validate_and_redeem(
        db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
        order_subtotal_aed=Decimal("50.00"), idempotency_key="r1",
    )
    with pytest.raises(CouponError):
        await c.validate_and_redeem(
            db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=2,
            order_subtotal_aed=Decimal("50.00"), idempotency_key="r2",
        )


async def test_total_limit_exhausts(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid, total_redemption_limit=1)
    await c.validate_and_redeem(
        db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
        order_subtotal_aed=Decimal("50.00"), idempotency_key="r1",
    )
    with pytest.raises(CouponError):
        await c.validate_and_redeem(
            db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=2,
            order_subtotal_aed=Decimal("50.00"), idempotency_key="r2",
        )


async def test_idempotent_replay_no_double_count(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid)
    a = await c.validate_and_redeem(
        db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
        order_subtotal_aed=Decimal("50.00"), idempotency_key="same",
    )
    b = await c.validate_and_redeem(
        db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
        order_subtotal_aed=Decimal("50.00"), idempotency_key="same",
    )
    assert a.id == b.id


async def test_paused_coupon_rejected(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    cp = await _coupon(db_session, rid)
    await c.pause_coupon(db_session, restaurant_id=rid, code=cp.code, created_by="mgr:1")
    with pytest.raises(CouponError):
        await c.validate_and_redeem(
            db_session, restaurant_id=rid, code=cp.code, customer_id=cid, order_id=1,
            order_subtotal_aed=Decimal("50.00"), idempotency_key="r1",
        )
