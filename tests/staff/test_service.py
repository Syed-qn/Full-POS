from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.staff.models import StaffMember
from app.staff.service import (
    AlreadyClockedInError,
    NotClockedInError,
    AlreadyOnBreakError,
    NotOnBreakError,
    clock_in,
    clock_out,
    start_break,
    end_break,
    compute_hours,
    compute_sales,
)


@pytest.mark.anyio
async def test_clock_in_then_out_computes_hours(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Ali", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()

    in_time = datetime.now(timezone.utc) - timedelta(hours=8)
    out_time = datetime.now(timezone.utc)

    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=in_time)
    await db_session.commit()
    await clock_out(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=out_time)
    await db_session.commit()

    hours = await compute_hours(db_session, staff_id=staff.id, restaurant_id=restaurant.id, target_date=date.today())
    assert hours == pytest.approx(8.0, abs=0.01)


@pytest.mark.anyio
async def test_double_clock_in_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Sara", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    with pytest.raises(AlreadyClockedInError):
        await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))


@pytest.mark.anyio
async def test_clock_out_without_clock_in_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Omar", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    await db_session.commit()
    with pytest.raises(NotClockedInError):
        await clock_out(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))


@pytest.mark.anyio
async def test_compute_sales_sums_orders_for_staff_today(db_session, restaurant):
    from app.ordering.models import Customer, Order

    staff = StaffMember(restaurant_id=restaurant.id, name="Layla", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000033", name="Cust")
    db_session.add(cust)
    await db_session.flush()
    o1 = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="S-0001",
        status="delivered", subtotal=Decimal("40.00"), total=Decimal("40.00"), staff_id=staff.id,
    )
    o2 = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number="S-0002",
        status="delivered", subtotal=Decimal("25.00"), total=Decimal("25.00"), staff_id=staff.id,
    )
    db_session.add_all([o1, o2])
    await db_session.commit()

    total = await compute_sales(db_session, staff_id=staff.id, restaurant_id=restaurant.id, target_date=date.today())
    assert total == Decimal("65.00")


@pytest.mark.anyio
async def test_break_time_is_subtracted_from_hours(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Huda", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()

    base = datetime.now(timezone.utc) - timedelta(hours=9)
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=base)
    await db_session.commit()
    await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=base + timedelta(hours=4))
    await db_session.commit()
    await end_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=base + timedelta(hours=5))
    await db_session.commit()
    await clock_out(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=base + timedelta(hours=9))
    await db_session.commit()

    hours = await compute_hours(db_session, staff_id=staff.id, restaurant_id=restaurant.id, target_date=date.today())
    assert hours == pytest.approx(8.0, abs=0.01)


@pytest.mark.anyio
async def test_break_start_without_clock_in_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Nadia", pin_hash="x")
    db_session.add(staff)
    await db_session.commit()
    with pytest.raises(NotClockedInError):
        await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))


@pytest.mark.anyio
async def test_double_break_start_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Yousef", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    with pytest.raises(AlreadyOnBreakError):
        await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))


@pytest.mark.anyio
async def test_clock_in_while_on_break_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Tariq", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    await start_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    with pytest.raises(AlreadyClockedInError):
        await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))


@pytest.mark.anyio
async def test_break_end_without_break_start_rejected(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Rania", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()
    await clock_in(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
    await db_session.commit()
    with pytest.raises(NotOnBreakError):
        await end_break(db_session, staff_id=staff.id, restaurant_id=restaurant.id, at=datetime.now(timezone.utc))
