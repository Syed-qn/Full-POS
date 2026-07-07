from datetime import date, datetime, timezone

import pytest

from app.staff.models import StaffMember
from app.staff.scheduling import create_shift, list_shifts_for_week


@pytest.mark.anyio
async def test_create_shift_persists_row(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Ali", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()

    start = datetime(2026, 7, 6, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 7, 6, 17, 0, tzinfo=timezone.utc)

    shift = await create_shift(
        db_session, restaurant_id=restaurant.id, staff_id=staff.id,
        scheduled_start=start, scheduled_end=end,
    )
    await db_session.commit()

    assert shift.id is not None
    assert shift.staff_id == staff.id
    assert shift.scheduled_start == start
    assert shift.scheduled_end == end


@pytest.mark.anyio
async def test_list_shifts_for_week_scopes_to_week_and_restaurant(db_session, restaurant):
    staff = StaffMember(restaurant_id=restaurant.id, name="Sara", pin_hash="x")
    db_session.add(staff)
    await db_session.flush()

    week_start = date(2026, 7, 6)  # Monday

    in_week = await create_shift(
        db_session, restaurant_id=restaurant.id, staff_id=staff.id,
        scheduled_start=datetime(2026, 7, 8, 9, 0, tzinfo=timezone.utc),
        scheduled_end=datetime(2026, 7, 8, 17, 0, tzinfo=timezone.utc),
    )
    await create_shift(
        db_session, restaurant_id=restaurant.id, staff_id=staff.id,
        scheduled_start=datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc),  # next Monday, out of week
        scheduled_end=datetime(2026, 7, 13, 17, 0, tzinfo=timezone.utc),
    )
    await db_session.commit()

    shifts = await list_shifts_for_week(db_session, restaurant_id=restaurant.id, week_start=week_start)
    assert [s.id for s in shifts] == [in_week.id]


@pytest.mark.anyio
async def test_create_shift_router_manager_only(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Manager Ali", "role": "manager", "pin": "9999"},
        headers=auth_headers,
    )
    manager_id = resp.json()["id"]
    resp_staff = await client.post(
        "/api/v1/staff", json={"name": "Cook Sam", "role": "kitchen", "pin": "1111"},
        headers=auth_headers,
    )
    staff_id = resp_staff.json()["id"]

    login = await client.post("/api/v1/staff/login", json={"staff_id": manager_id, "pin": "9999"})
    manager_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    login_kitchen = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "1111"})
    kitchen_headers = {"Authorization": f"Bearer {login_kitchen.json()['access_token']}"}

    body = {
        "staff_id": staff_id,
        "scheduled_start": "2026-07-06T09:00:00Z",
        "scheduled_end": "2026-07-06T17:00:00Z",
    }

    denied = await client.post("/api/v1/staff/shifts", json=body, headers=kitchen_headers)
    assert denied.status_code == 403

    created = await client.post("/api/v1/staff/shifts", json=body, headers=manager_headers)
    assert created.status_code == 201
    assert created.json()["staff_id"] == staff_id


@pytest.mark.anyio
async def test_list_shifts_for_week_router(client, auth_headers):
    resp_staff = await client.post(
        "/api/v1/staff", json={"name": "Bilal", "pin": "5678"}, headers=auth_headers,
    )
    staff_id = resp_staff.json()["id"]

    body = {
        "staff_id": staff_id,
        "scheduled_start": "2026-07-06T09:00:00Z",
        "scheduled_end": "2026-07-06T17:00:00Z",
    }
    await client.post("/api/v1/staff/shifts", json=body, headers=auth_headers)

    listing = await client.get("/api/v1/staff/shifts?week_start=2026-07-06", headers=auth_headers)
    assert listing.status_code == 200
    assert len(listing.json()) == 1
    assert listing.json()[0]["staff_id"] == staff_id

    empty = await client.get("/api/v1/staff/shifts?week_start=2026-07-13", headers=auth_headers)
    assert empty.status_code == 200
    assert empty.json() == []
