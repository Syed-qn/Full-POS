"""Delivery OTP: auto-generated at 'arriving', verified informationally (no FSM gate)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.dispatch.delivery import advance_delivery
from app.dispatch.delivery_proof import (
    OtpVerificationError,
    generate_delivery_otp,
    verify_delivery_otp,
)
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, Order


async def _seed(db_session, status="assigned", *, batched=True):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(
        restaurant_id=r.id,
        name="X",
        phone="+971500000010",
        status="on_delivery",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 0},
    )
    db_session.add(rider)
    await db_session.flush()
    c = Customer(
        restaurant_id=r.id,
        phone="+971501112233",
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
        status=status,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
        rider_id=rider.id,
        sla_deadline=datetime.now(timezone.utc) + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    if batched:
        batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="picked_up", route={"stops": []})
        db_session.add(batch)
        await db_session.flush()
        db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=1))
    await db_session.commit()
    return r, rider, o


async def test_generate_delivery_otp_is_four_digits(db_session):
    r, rider, o = await _seed(db_session, status="picked_up")
    otp = await generate_delivery_otp(db_session, order=o)
    await db_session.commit()
    assert len(otp) == 4
    assert otp.isdigit()
    assert o.delivery_otp == otp


async def test_advance_to_arriving_generates_otp(db_session):
    r, rider, o = await _seed(db_session, status="picked_up")
    await advance_delivery(db_session, order_id=o.id, to_status="arriving")
    await db_session.commit()
    await db_session.refresh(o)
    assert o.delivery_otp is not None
    assert len(o.delivery_otp) == 4


async def test_advance_to_delivered_does_not_require_otp_verification(db_session):
    """OTP verification is informational — it must never block delivered."""
    r, rider, o = await _seed(db_session, status="arriving")
    o.delivery_otp = "1234"
    await db_session.commit()
    await advance_delivery(db_session, order_id=o.id, to_status="delivered")
    await db_session.commit()
    await db_session.refresh(o)
    assert o.status == "delivered"
    assert o.delivery_otp_verified_at is None


async def test_verify_delivery_otp_correct_code(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    o.delivery_otp = "4242"
    await db_session.commit()
    result = await verify_delivery_otp(
        db_session, restaurant_id=r.id, order_id=o.id, otp="4242"
    )
    await db_session.commit()
    await db_session.refresh(o)
    assert result is True
    assert o.delivery_otp_verified_at is not None


async def test_verify_delivery_otp_wrong_code_raises(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    o.delivery_otp = "4242"
    await db_session.commit()
    with pytest.raises(OtpVerificationError):
        await verify_delivery_otp(
            db_session, restaurant_id=r.id, order_id=o.id, otp="0000"
        )
    await db_session.refresh(o)
    assert o.delivery_otp_verified_at is None


async def test_verify_delivery_otp_foreign_tenant_raises(db_session):
    r, rider, o = await _seed(db_session, status="arriving")
    o.delivery_otp = "4242"
    await db_session.commit()
    with pytest.raises(OtpVerificationError):
        await verify_delivery_otp(
            db_session, restaurant_id=r.id + 999, order_id=o.id, otp="4242"
        )
