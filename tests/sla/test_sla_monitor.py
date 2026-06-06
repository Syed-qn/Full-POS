"""SLA monitor tests — importable models + monitor logic integration tests."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.models import CodCollection, RiderShiftReconciliation
from app.coupons.models import Coupon
from app.identity.models import Restaurant
from app.ordering.models import Customer, Order
from app.outbox.models import OutboxMessage
from app.sla.models import SlaEvent
from app.sla.monitor import _run_monitor


# ---------------------------------------------------------------------------
# Original smoke tests
# ---------------------------------------------------------------------------

def test_sla_event_importable():
    assert SlaEvent.__tablename__ == "sla_events"


def test_coupon_importable():
    assert Coupon.__tablename__ == "coupons"


def test_cod_collection_importable():
    assert CodCollection.__tablename__ == "cod_collections"


def test_reconciliation_importable():
    assert RiderShiftReconciliation.__tablename__ == "rider_shift_reconciliations"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _seed_restaurant(session: AsyncSession) -> Restaurant:
    r = Restaurant(
        name="SLA Test Restaurant",
        phone="+971509999000",
        password_hash="hashed",
        lat=25.2048,
        lng=55.2708,
    )
    session.add(r)
    await session.flush()
    return r


async def _seed_customer(session: AsyncSession, restaurant_id: int, idx: int = 0) -> Customer:
    c = Customer(
        restaurant_id=restaurant_id,
        phone=f"+9715088{idx:05d}",
        name=f"Customer{idx}",
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    session.add(c)
    await session.flush()
    return c


async def _seed_order(
    session: AsyncSession,
    restaurant_id: int,
    customer_id: int,
    *,
    elapsed_minutes: float,
    weather_delay_disclosed: bool = False,
    status: str = "confirmed",
    idx: int = 1,
) -> Order:
    sla_confirmed_at = datetime.now(timezone.utc) - timedelta(minutes=elapsed_minutes)
    o = Order(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_number=f"TEST{idx:04d}",
        status=status,
        priority="normal",
        weather_delay_disclosed=weather_delay_disclosed,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("20.00"),
        total=Decimal("20.00"),
        sla_confirmed_at=sla_confirmed_at,
    )
    session.add(o)
    await session.flush()
    return o


def _make_session_factory(session: AsyncSession):
    """Create a context-manager factory that yields the provided session."""
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _factory():
        yield session

    return _factory


# ---------------------------------------------------------------------------
# Monitor integration tests
# ---------------------------------------------------------------------------

async def test_yellow_30_fires_at_30_min(db_session: AsyncSession):
    """Order at 31 minutes elapsed → only yellow_30 event created."""
    r = await _seed_restaurant(db_session)
    c = await _seed_customer(db_session, r.id, idx=100)
    order = await _seed_order(db_session, r.id, c.id, elapsed_minutes=31.0, idx=1)
    await db_session.commit()

    with patch("app.sla.monitor.async_session_factory", _make_session_factory(db_session)):
        await _run_monitor()

    events = (
        await db_session.scalars(
            select(SlaEvent).where(SlaEvent.order_id == order.id)
        )
    ).all()
    event_types = {e.type for e in events}
    assert "yellow_30" in event_types
    assert "red_35" not in event_types
    assert "breach_40" not in event_types


async def test_red_35_and_yellow_30_both_fire_at_36_min(db_session: AsyncSession):
    """Order at 36 minutes → yellow_30 and red_35 both created (not breach_40)."""
    r = await _seed_restaurant(db_session)
    c = await _seed_customer(db_session, r.id, idx=200)
    order = await _seed_order(db_session, r.id, c.id, elapsed_minutes=36.0, idx=2)
    await db_session.commit()

    with patch("app.sla.monitor.async_session_factory", _make_session_factory(db_session)):
        await _run_monitor()

    events = (
        await db_session.scalars(
            select(SlaEvent).where(SlaEvent.order_id == order.id)
        )
    ).all()
    event_types = {e.type for e in events}
    assert "yellow_30" in event_types
    assert "red_35" in event_types
    assert "breach_40" not in event_types


async def test_breach_40_creates_coupon(db_session: AsyncSession):
    """Order at 41 minutes + weather_delay_disclosed=False → coupon issued."""
    r = await _seed_restaurant(db_session)
    c = await _seed_customer(db_session, r.id, idx=300)
    order = await _seed_order(
        db_session,
        r.id,
        c.id,
        elapsed_minutes=41.0,
        weather_delay_disclosed=False,
        idx=3,
    )
    await db_session.commit()

    with patch("app.sla.monitor.async_session_factory", _make_session_factory(db_session)):
        await _run_monitor()

    # All three events should have fired
    events = (
        await db_session.scalars(
            select(SlaEvent).where(SlaEvent.order_id == order.id)
        )
    ).all()
    event_types = {e.type for e in events}
    assert "yellow_30" in event_types
    assert "red_35" in event_types
    assert "breach_40" in event_types

    # Coupon must be issued
    coupon = await db_session.scalar(
        select(Coupon).where(Coupon.order_id == order.id)
    )
    assert coupon is not None
    assert coupon.discount_aed == Decimal("10.00")
    assert coupon.status == "issued"


async def test_breach_40_skips_coupon_if_weather(db_session: AsyncSession):
    """Order at 41 minutes + weather_delay_disclosed=True → breach event fires but NO coupon."""
    r = await _seed_restaurant(db_session)
    c = await _seed_customer(db_session, r.id, idx=400)
    order = await _seed_order(
        db_session,
        r.id,
        c.id,
        elapsed_minutes=41.0,
        weather_delay_disclosed=True,
        idx=4,
    )
    await db_session.commit()

    with patch("app.sla.monitor.async_session_factory", _make_session_factory(db_session)):
        await _run_monitor()

    events = (
        await db_session.scalars(
            select(SlaEvent).where(SlaEvent.order_id == order.id)
        )
    ).all()
    event_types = {e.type for e in events}
    assert "breach_40" in event_types  # event still fires

    # But NO coupon issued
    coupon = await db_session.scalar(
        select(Coupon).where(Coupon.order_id == order.id)
    )
    assert coupon is None


async def test_monitor_idempotent_second_run_no_duplicates(db_session: AsyncSession):
    """Running the monitor twice for the same order does NOT create duplicate SlaEvent rows."""
    r = await _seed_restaurant(db_session)
    c = await _seed_customer(db_session, r.id, idx=500)
    order = await _seed_order(db_session, r.id, c.id, elapsed_minutes=31.0, idx=5)
    await db_session.commit()

    with patch("app.sla.monitor.async_session_factory", _make_session_factory(db_session)):
        await _run_monitor()
        await _run_monitor()  # second run — should not error or duplicate

    events = (
        await db_session.scalars(
            select(SlaEvent).where(
                SlaEvent.order_id == order.id,
                SlaEvent.type == "yellow_30",
            )
        )
    ).all()
    assert len(events) == 1  # exactly one, not two


async def test_order_without_sla_confirmed_at_skipped(db_session: AsyncSession):
    """Orders with no sla_confirmed_at must be silently skipped."""
    r = await _seed_restaurant(db_session)
    c = await _seed_customer(db_session, r.id, idx=600)
    # Manually create order without sla_confirmed_at
    order = Order(
        restaurant_id=r.id,
        customer_id=c.id,
        order_number="NOSLA001",
        status="confirmed",
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("20.00"),
        total=Decimal("20.00"),
        sla_confirmed_at=None,
    )
    db_session.add(order)
    await db_session.commit()

    with patch("app.sla.monitor.async_session_factory", _make_session_factory(db_session)):
        await _run_monitor()

    events = (
        await db_session.scalars(
            select(SlaEvent).where(SlaEvent.order_id == order.id)
        )
    ).all()
    assert len(events) == 0


async def test_manager_outbox_message_created_on_yellow_30(db_session: AsyncSession):
    """yellow_30 must enqueue manager alert outbox message."""
    r = await _seed_restaurant(db_session)
    c = await _seed_customer(db_session, r.id, idx=700)
    order = await _seed_order(db_session, r.id, c.id, elapsed_minutes=31.0, idx=7)
    await db_session.commit()

    with patch("app.sla.monitor.async_session_factory", _make_session_factory(db_session)):
        await _run_monitor()

    mgr_msg = await db_session.scalar(
        select(OutboxMessage).where(
            OutboxMessage.to_phone == r.phone,
            OutboxMessage.idempotency_key == f"sla-mgr-{order.id}-yellow_30",
        )
    )
    assert mgr_msg is not None


async def test_customer_outbox_message_created_on_breach_40(db_session: AsyncSession):
    """breach_40 must enqueue customer alert outbox message."""
    r = await _seed_restaurant(db_session)
    c = await _seed_customer(db_session, r.id, idx=800)
    order = await _seed_order(
        db_session, r.id, c.id, elapsed_minutes=41.0, weather_delay_disclosed=True, idx=8
    )
    await db_session.commit()

    with patch("app.sla.monitor.async_session_factory", _make_session_factory(db_session)):
        await _run_monitor()

    cust_msg = await db_session.scalar(
        select(OutboxMessage).where(
            OutboxMessage.to_phone == c.phone,
            OutboxMessage.idempotency_key == f"sla-cust-{order.id}-breach_40",
        )
    )
    assert cust_msg is not None
