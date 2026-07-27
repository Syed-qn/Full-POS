"""Edit / remove a non-manager staff member (waiter). Managers are excluded —
they belong to the owner-only Manager Management surface."""

import pytest

from tests.helpers import store_key


async def _restaurant(db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


@pytest.mark.anyio
async def test_edit_and_remove_waiter(client, auth_headers, db_session):
    from app.identity.auth import hash_password
    from app.staff.models import StaffMember

    restaurant = await _restaurant(db_session)
    w = StaffMember(
        restaurant_id=restaurant.id, name="Wal", role="waiter",
        pin_hash=hash_password("1176"), is_active=True,
    )
    db_session.add(w)
    await db_session.commit()

    # Edit name + reset PIN.
    resp = await client.patch(
        f"/api/v1/staff/{w.id}",
        json={"name": "Wal Ali", "pin": "2468"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Wal Ali"

    login = await client.post("/api/v1/staff/login", json={"store": await store_key(client, auth_headers), "staff_id": w.id, "pin": "2468"})
    assert login.status_code == 200

    # Remove (soft delete) → login rejected afterwards.
    deleted = await client.delete(f"/api/v1/staff/{w.id}", headers=auth_headers)
    assert deleted.status_code == 204
    relogin = await client.post("/api/v1/staff/login", json={"store": await store_key(client, auth_headers), "staff_id": w.id, "pin": "2468"})
    assert relogin.status_code == 401


@pytest.mark.anyio
async def test_generic_edit_rejects_manager(client, auth_headers, db_session):
    from app.identity.auth import hash_password
    from app.staff.models import StaffMember

    restaurant = await _restaurant(db_session)
    mgr = StaffMember(
        restaurant_id=restaurant.id, name="Boss", role="manager",
        pin_hash=hash_password("1176"), is_active=True,
    )
    db_session.add(mgr)
    await db_session.commit()

    patched = await client.patch(
        f"/api/v1/staff/{mgr.id}", json={"name": "X"}, headers=auth_headers
    )
    assert patched.status_code == 409
    removed = await client.delete(f"/api/v1/staff/{mgr.id}", headers=auth_headers)
    assert removed.status_code == 409
