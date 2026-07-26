"""Owner-only manager management: an owner (restaurant account or role=owner
staff) can CRUD managers; a manager token is forbidden."""

import pytest


async def _restaurant(db_session):
    from sqlalchemy import select

    from app.identity.models import Restaurant

    return await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )


def _staff_headers(staff_id: int, role: str) -> dict:
    from app.identity.auth import create_access_token

    token = create_access_token(
        staff_id=staff_id, audience="staff", extra_claims={"role": role}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_owner_can_crud_managers(client, auth_headers, db_session):
    # auth_headers is the restaurant OWNER account token (aud=manager).
    created = await client.post(
        "/api/v1/staff/managers",
        json={"name": "Sara", "phone": "+971500000010", "pin": "4321"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    mid = created.json()["id"]
    assert created.json()["role"] == "manager"

    listing = await client.get("/api/v1/staff/managers", headers=auth_headers)
    assert listing.status_code == 200
    assert any(m["id"] == mid and m["name"] == "Sara" for m in listing.json())

    patched = await client.patch(
        f"/api/v1/staff/managers/{mid}",
        json={"name": "Sara Ali", "pin": "9999"},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Sara Ali"

    # New PIN works for login.
    login = await client.post(
        "/api/v1/staff/login", json={"staff_id": mid, "pin": "9999"}
    )
    assert login.status_code == 200
    assert login.json()["role"] == "manager"

    # Delete = deactivate → drops out of the active list.
    deleted = await client.delete(
        f"/api/v1/staff/managers/{mid}", headers=auth_headers
    )
    assert deleted.status_code == 204
    listing2 = await client.get("/api/v1/staff/managers", headers=auth_headers)
    assert all(m["id"] != mid for m in listing2.json())
    # Deactivated → login now rejected.
    relogin = await client.post(
        "/api/v1/staff/login", json={"staff_id": mid, "pin": "9999"}
    )
    assert relogin.status_code == 401


@pytest.mark.anyio
async def test_manager_role_is_forbidden(client, auth_headers, db_session):
    from app.identity.auth import hash_password
    from app.staff.models import StaffMember

    restaurant = await _restaurant(db_session)
    boss = StaffMember(
        restaurant_id=restaurant.id, name="Boss", role="manager",
        pin_hash=hash_password("1111"), is_active=True,
    )
    db_session.add(boss)
    await db_session.commit()
    hdr = _staff_headers(boss.id, "manager")

    # A manager cannot list or create managers — owner-only.
    assert (await client.get("/api/v1/staff/managers", headers=hdr)).status_code == 403
    forbidden = await client.post(
        "/api/v1/staff/managers",
        json={"name": "X", "pin": "2222"},
        headers=hdr,
    )
    assert forbidden.status_code == 403


@pytest.mark.anyio
async def test_owner_role_staff_can_manage(client, auth_headers, db_session):
    from app.identity.auth import hash_password
    from app.staff.models import StaffMember

    restaurant = await _restaurant(db_session)
    owner = StaffMember(
        restaurant_id=restaurant.id, name="Owner", role="owner",
        pin_hash=hash_password("1234"), is_active=True,
    )
    db_session.add(owner)
    await db_session.commit()
    hdr = _staff_headers(owner.id, "owner")

    resp = await client.post(
        "/api/v1/staff/managers",
        json={"name": "New Mgr", "pin": "5555"},
        headers=hdr,
    )
    assert resp.status_code == 201, resp.text
