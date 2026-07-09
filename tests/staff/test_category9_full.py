"""Category 9 — staff & permissions full wiring tests."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest


@pytest.mark.anyio
async def test_manager_pin_approval(db_session, restaurant):
    from app.identity.auth import hash_password
    from app.staff.approvals import InvalidManagerPinError, approve_with_pin
    from app.staff.models import StaffMember

    mgr = StaffMember(
        restaurant_id=restaurant.id,
        name="Boss",
        role="manager",
        pin_hash=hash_password("9999"),
        is_active=True,
    )
    db_session.add(mgr)
    await db_session.flush()

    row = await approve_with_pin(
        db_session,
        restaurant=restaurant,
        action_type="discount",
        pin="9999",
        amount_aed=Decimal("25.00"),
        reason="VIP",
    )
    assert row.status == "approved"
    assert row.approved_by_staff_id == mgr.id

    with pytest.raises(InvalidManagerPinError):
        await approve_with_pin(
            db_session,
            restaurant=restaurant,
            action_type="void",
            pin="0000",
        )


@pytest.mark.anyio
async def test_shift_open_close_and_attendance(db_session, restaurant):
    from app.identity.auth import hash_password
    from app.staff.models import StaffMember
    from app.staff.performance import attendance_for_date
    from app.staff.scheduling import close_shift, create_shift, open_shift
    from app.staff.service import clock_in, clock_out

    staff = StaffMember(
        restaurant_id=restaurant.id,
        name="Ali",
        role="staff",
        pin_hash=hash_password("1234"),
    )
    db_session.add(staff)
    await db_session.flush()

    start = datetime.now(timezone.utc).replace(hour=9, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=8)
    shift = await create_shift(
        db_session,
        restaurant_id=restaurant.id,
        staff_id=staff.id,
        scheduled_start=start,
        scheduled_end=end,
    )
    opened = await open_shift(db_session, restaurant_id=restaurant.id, shift_id=shift.id)
    assert opened.status == "open"
    assert opened.actual_start is not None

    await clock_in(
        db_session,
        staff_id=staff.id,
        restaurant_id=restaurant.id,
        at=start + timedelta(minutes=5),
    )
    await clock_out(
        db_session,
        staff_id=staff.id,
        restaurant_id=restaurant.id,
        at=start + timedelta(hours=8),
    )
    closed = await close_shift(db_session, restaurant_id=restaurant.id, shift_id=shift.id)
    assert closed.status == "closed"

    rows = await attendance_for_date(
        db_session, restaurant_id=restaurant.id, target_date=date.today()
    )
    ali = next(r for r in rows if r["staff_id"] == staff.id)
    assert ali["attendance_status"] in ("present", "unscheduled_work")
    assert ali["worked_hours"] > 0


@pytest.mark.anyio
async def test_mistake_training_tips_performance(db_session, restaurant):
    from app.identity.auth import hash_password
    from app.ordering.models import Customer, Order
    from app.payments.models import PaymentTransaction
    from app.staff.mistakes import record_mistake
    from app.staff.models import StaffMember
    from app.staff.performance import performance_report
    from app.staff.service import set_training_mode
    from app.staff.tips import attribute_tip_to_staff, tips_by_staff

    staff = StaffMember(
        restaurant_id=restaurant.id,
        name="Sara",
        role="staff",
        pin_hash=hash_password("1111"),
    )
    db_session.add(staff)
    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500009901",
        name="C",
        total_orders=0,
        total_spend=Decimal("0"),
    )
    db_session.add(cust)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C9-TIP-1",
        status="delivered",
        subtotal=Decimal("50"),
        total=Decimal("50"),
        staff_id=staff.id,
        is_training=False,
    )
    db_session.add(order)
    await db_session.flush()

    db_session.add(
        PaymentTransaction(
            restaurant_id=restaurant.id,
            order_id=order.id,
            amount_aed=Decimal("50"),
            tip_aed=Decimal("10"),
            status="succeeded",
            tender_type="cash",
            provider="manual",
        )
    )
    await attribute_tip_to_staff(
        db_session,
        restaurant_id=restaurant.id,
        order_id=order.id,
        staff_id=staff.id,
    )
    await record_mistake(
        db_session,
        restaurant_id=restaurant.id,
        staff_id=staff.id,
        mistake_type="wrong_item",
        order_id=order.id,
        amount_aed=Decimal("5.00"),
        notes="sent wrong wrap",
    )
    await db_session.commit()

    today = date.today()
    by = await tips_by_staff(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    assert by[staff.id] == Decimal("10.00")

    perf = await performance_report(
        db_session, restaurant_id=restaurant.id, start_date=today, end_date=today
    )
    row = next(r for r in perf if r["staff_id"] == staff.id)
    assert row["mistake_count"] == 1
    assert Decimal(row["tips_aed"]) == Decimal("10.00")

    await set_training_mode(
        db_session, restaurant_id=restaurant.id, staff_id=staff.id, training_mode=True
    )
    await db_session.commit()
    refreshed = await db_session.get(StaffMember, staff.id)
    assert refreshed.training_mode is True


@pytest.mark.anyio
async def test_cash_drawer_staff_assignment(db_session, restaurant):
    from decimal import Decimal

    from app.cashdrawer.service import open_session
    from app.identity.auth import hash_password
    from app.staff.models import StaffMember

    staff = StaffMember(
        restaurant_id=restaurant.id,
        name="Cashier",
        role="staff",
        pin_hash=hash_password("2222"),
    )
    db_session.add(staff)
    await db_session.flush()

    drawer = await open_session(
        db_session,
        restaurant_id=restaurant.id,
        opened_by=f"staff:{staff.id}",
        opening_float_aed=Decimal("200.00"),
        staff_id=staff.id,
    )
    assert drawer.staff_id == staff.id


@pytest.mark.anyio
async def test_api_staff_cat9_endpoints(client, auth_headers, restaurant):
    # Create staff
    create = await client.post(
        "/api/v1/staff",
        headers=auth_headers,
        json={"name": "C9 Worker", "pin": "4321", "role": "staff"},
    )
    assert create.status_code == 201, create.text
    staff_id = create.json()["id"]

    # Manager for PIN
    mgr = await client.post(
        "/api/v1/staff",
        headers=auth_headers,
        json={"name": "C9 Mgr", "pin": "8888", "role": "manager"},
    )
    assert mgr.status_code == 201
    mgr_id = mgr.json()["id"]

    # Login
    login = await client.post(
        "/api/v1/staff/login",
        json={"staff_id": staff_id, "pin": "4321"},
    )
    assert login.status_code == 200
    assert login.json()["role"] == "staff"

    # Clock + break
    assert (
        await client.post(
            f"/api/v1/staff/{staff_id}/clock",
            headers=auth_headers,
            json={"type": "clock_in"},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/staff/{staff_id}/clock",
            headers=auth_headers,
            json={"type": "break_start"},
        )
    ).status_code == 200
    assert (
        await client.post(
            f"/api/v1/staff/{staff_id}/clock",
            headers=auth_headers,
            json={"type": "break_end"},
        )
    ).status_code == 200

    # Training mode
    train = await client.patch(
        f"/api/v1/staff/{staff_id}/training-mode",
        headers=auth_headers,
        json={"training_mode": True},
    )
    assert train.status_code == 200
    assert train.json()["training_mode"] is True

    # Approval with manager pin
    appr = await client.post(
        "/api/v1/staff/approvals",
        headers=auth_headers,
        json={
            "pin": "8888",
            "action_type": "discount",
            "amount_aed": "30.00",
            "reason": "test",
            "requested_by_staff_id": staff_id,
        },
    )
    assert appr.status_code == 201, appr.text
    assert appr.json()["status"] == "approved"

    # Mistake
    mist = await client.post(
        "/api/v1/staff/mistakes",
        headers=auth_headers,
        json={
            "staff_id": staff_id,
            "mistake_type": "spill",
            "amount_aed": "3.00",
            "notes": "dropped tray",
        },
    )
    assert mist.status_code == 201, mist.text

    today = date.today().isoformat()
    att = await client.get(
        f"/api/v1/staff/attendance?target_date={today}",
        headers=auth_headers,
    )
    assert att.status_code == 200
    assert "rows" in att.json()

    perf = await client.get(
        f"/api/v1/staff/reports/performance?start_date={today}&end_date={today}",
        headers=auth_headers,
    )
    assert perf.status_code == 200
    assert "rows" in perf.json()

    # Shift schedule open/close
    start = datetime.now(timezone.utc).isoformat()
    end = (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()
    sh = await client.post(
        "/api/v1/staff/shifts",
        headers=auth_headers,
        json={
            "staff_id": mgr_id,
            "scheduled_start": start,
            "scheduled_end": end,
        },
    )
    assert sh.status_code == 201, sh.text
    shift_id = sh.json()["id"]
    # Clock out worker first if needed for mgr shift open
    await client.post(
        f"/api/v1/staff/{staff_id}/clock",
        headers=auth_headers,
        json={"type": "clock_out"},
    )
    op = await client.post(
        f"/api/v1/staff/shifts/{shift_id}/open",
        headers=auth_headers,
    )
    assert op.status_code == 200, op.text
    assert op.json()["status"] == "open"
    cl = await client.post(
        f"/api/v1/staff/shifts/{shift_id}/close",
        headers=auth_headers,
    )
    assert cl.status_code == 200
    assert cl.json()["status"] == "closed"

    # Drawer with staff assignment
    drawer = await client.post(
        "/api/v1/cash-drawer/sessions",
        headers=auth_headers,
        json={"opening_float_aed": "100.00", "staff_id": staff_id},
    )
    assert drawer.status_code == 201, drawer.text
    assert drawer.json().get("staff_id") == staff_id

    alerts = await client.get("/api/v1/staff/alerts", headers=auth_headers)
    assert alerts.status_code == 200
