from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.ordering.models import Customer, Order
from app.payments.models import PaymentTransaction
from app.staff.models import StaffMember
from app.staff.service import clock_in
from app.staff.tips import distribute_tip_pool


async def _seed_delivered_order_with_tip(db_session, restaurant, *, tip: Decimal, when: datetime, order_number: str):
    cust = Customer(restaurant_id=restaurant.id, phone=f"+9715000000{order_number[-2:]}", name="Cust")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number=order_number,
        status="delivered", subtotal=Decimal("40.00"), total=Decimal("40.00"),
        delivered_at=when,
    )
    db_session.add(order)
    await db_session.flush()
    txn = PaymentTransaction(
        restaurant_id=restaurant.id, order_id=order.id, tender_type="cash",
        amount_aed=Decimal("40.00"), tip_aed=tip, status="succeeded",
    )
    db_session.add(txn)
    await db_session.flush()
    return order


@pytest.mark.anyio
async def test_distribute_tip_pool_splits_evenly_across_clocked_in_staff(db_session, restaurant):
    start_date = date(2026, 7, 6)
    end_date = date(2026, 7, 6)
    at = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    staff_a = StaffMember(restaurant_id=restaurant.id, name="Ali", pin_hash="x")
    staff_b = StaffMember(restaurant_id=restaurant.id, name="Sara", pin_hash="x")
    db_session.add_all([staff_a, staff_b])
    await db_session.flush()

    await clock_in(db_session, staff_id=staff_a.id, restaurant_id=restaurant.id, at=at)
    await clock_in(db_session, staff_id=staff_b.id, restaurant_id=restaurant.id, at=at)
    await db_session.commit()

    await _seed_delivered_order_with_tip(
        db_session, restaurant, tip=Decimal("10.00"), when=at, order_number="T-0001",
    )
    await _seed_delivered_order_with_tip(
        db_session, restaurant, tip=Decimal("20.00"), when=at, order_number="T-0002",
    )
    await db_session.commit()

    pool = await distribute_tip_pool(
        db_session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date,
    )

    assert pool == {staff_a.id: Decimal("15.00"), staff_b.id: Decimal("15.00")}


@pytest.mark.anyio
async def test_distribute_tip_pool_excludes_staff_not_clocked_in(db_session, restaurant):
    start_date = date(2026, 7, 6)
    end_date = date(2026, 7, 6)
    at = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    staff_a = StaffMember(restaurant_id=restaurant.id, name="Ali", pin_hash="x")
    staff_b = StaffMember(restaurant_id=restaurant.id, name="Not Working", pin_hash="x")
    db_session.add_all([staff_a, staff_b])
    await db_session.flush()

    await clock_in(db_session, staff_id=staff_a.id, restaurant_id=restaurant.id, at=at)
    await db_session.commit()

    await _seed_delivered_order_with_tip(
        db_session, restaurant, tip=Decimal("10.00"), when=at, order_number="T-0003",
    )
    await db_session.commit()

    pool = await distribute_tip_pool(
        db_session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date,
    )

    assert pool == {staff_a.id: Decimal("10.00")}


@pytest.mark.anyio
async def test_distribute_tip_pool_empty_when_no_tips(db_session, restaurant):
    start_date = date(2026, 7, 6)
    end_date = date(2026, 7, 6)

    staff_a = StaffMember(restaurant_id=restaurant.id, name="Ali", pin_hash="x")
    db_session.add(staff_a)
    await db_session.flush()
    await clock_in(
        db_session, staff_id=staff_a.id, restaurant_id=restaurant.id,
        at=datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
    )
    await db_session.commit()

    pool = await distribute_tip_pool(
        db_session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date,
    )
    assert pool == {}


@pytest.mark.anyio
async def test_tip_pool_router_manager_only(client, auth_headers):
    resp_staff = await client.post(
        "/api/v1/staff", json={"name": "Cook Sam", "role": "kitchen", "pin": "1111"},
        headers=auth_headers,
    )
    staff_id = resp_staff.json()["id"]
    login_kitchen = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "1111"})
    kitchen_headers = {"Authorization": f"Bearer {login_kitchen.json()['access_token']}"}

    denied = await client.get(
        "/api/v1/staff/tip-pool?start_date=2026-07-06&end_date=2026-07-06", headers=kitchen_headers,
    )
    assert denied.status_code == 403

    allowed = await client.get(
        "/api/v1/staff/tip-pool?start_date=2026-07-06&end_date=2026-07-06", headers=auth_headers,
    )
    assert allowed.status_code == 200
    assert allowed.json() == {}
