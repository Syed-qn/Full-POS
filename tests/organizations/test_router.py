from datetime import date

import pytest


@pytest.mark.anyio
async def test_owner_bootstrap_links_restaurant_and_allows_branches(
    client, auth_headers, db_session
):
    """Restaurant owner (aud=manager) can bootstrap multi-branch HQ without a
    second org email/password, then add a sister branch under the same org."""
    from sqlalchemy import select

    from app.identity.models import Restaurant

    boot = await client.post("/api/v1/organizations/bootstrap", headers=auth_headers)
    assert boot.status_code == 200, boot.text
    body = boot.json()
    assert body["created"] is True
    assert body["access_token"]
    org_id = body["id"]
    restaurant_id = body["restaurant_id"]

    # Idempotent — second call does not create another org.
    boot2 = await client.post("/api/v1/organizations/bootstrap", headers=auth_headers)
    assert boot2.status_code == 200
    assert boot2.json()["created"] is False
    assert boot2.json()["id"] == org_id

    restaurant = await db_session.get(Restaurant, restaurant_id)
    assert restaurant is not None
    assert restaurant.organization_id == org_id

    org_headers = {"Authorization": f"Bearer {body['access_token']}"}
    sister = await client.post(
        "/api/v1/organizations/branches",
        json={"name": "Sister Branch", "email": "branch_33966923@test.local", "password": "hunter2!", "lat": 25.3, "lng": 55.3, "region": "Dubai"},
        headers=org_headers,
    )
    assert sister.status_code == 201, sister.text

    listing = await client.get("/api/v1/organizations/branches", headers=org_headers)
    assert listing.status_code == 200
    names = {row["name"] for row in listing.json()}
    assert "Sister Branch" in names
    # Current restaurant is itself a branch of the org.
    assert any(row["id"] == restaurant_id for row in listing.json())

    # Owner restaurant token can hit org routes directly once linked (no org JWT).
    via_owner = await client.get(
        "/api/v1/organizations/branches", headers=auth_headers
    )
    assert via_owner.status_code == 200
    assert len(via_owner.json()) >= 2


@pytest.mark.anyio
async def test_branch_manager_cannot_bootstrap_or_list_hq(client, auth_headers, db_session):
    """Staff role=manager runs one store — multi-branch HQ is owner-only."""
    from app.identity.auth import create_access_token, hash_password
    from app.identity.models import Restaurant
    from app.staff.models import StaffMember
    from sqlalchemy import select

    restaurant = await db_session.scalar(
        select(Restaurant).where(Restaurant.email == "owner@biryani.ae")
    )
    assert restaurant is not None

    # Owner first links the store so org exists — manager still must not access HQ.
    boot = await client.post("/api/v1/organizations/bootstrap", headers=auth_headers)
    assert boot.status_code == 200

    manager = StaffMember(
        restaurant_id=restaurant.id,
        name="Branch Mgr",
        role="manager",
        pin_hash=hash_password("1286"),
        is_active=True,
    )
    db_session.add(manager)
    await db_session.commit()
    await db_session.refresh(manager)

    mgr_headers = {
        "Authorization": (
            f"Bearer {create_access_token(staff_id=manager.id, audience='staff', extra_claims={'role': 'manager'})}"
        )
    }

    denied_boot = await client.post(
        "/api/v1/organizations/bootstrap", headers=mgr_headers
    )
    assert denied_boot.status_code == 403

    denied_list = await client.get(
        "/api/v1/organizations/branches", headers=mgr_headers
    )
    assert denied_list.status_code == 403


@pytest.mark.anyio
async def test_signup_login_add_branch_and_rollup(client):
    signup = await client.post(
        "/api/v1/organizations/signup",
        json={"name": "Test Group", "owner_email": "owner@testgroup.ae", "password": "hunter2!"},
    )
    assert signup.status_code == 201
    token = signup.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    login = await client.post(
        "/api/v1/organizations/login",
        json={"owner_email": "owner@testgroup.ae", "password": "hunter2!"},
    )
    assert login.status_code == 200

    branch1 = await client.post(
        "/api/v1/organizations/branches",
        json={"name": "Branch A", "email": "branch_35043895@test.local", "password": "hunter2!", "lat": 25.1, "lng": 55.1}, headers=headers,
    )
    assert branch1.status_code == 201
    branch2 = await client.post(
        "/api/v1/organizations/branches",
        json={"name": "Branch B", "email": "branch_42907081@test.local", "password": "hunter2!", "lat": 25.2, "lng": 55.2}, headers=headers,
    )
    assert branch2.status_code == 201

    listing = await client.get("/api/v1/organizations/branches", headers=headers)
    assert len(listing.json()) == 2

    today = date.today().isoformat()
    rollup = await client.get(f"/api/v1/organizations/rollup-sales?target_date={today}", headers=headers)
    assert rollup.status_code == 200
    assert rollup.json()["total_gross_sales_aed"] == "0.00"
    assert len(rollup.json()["branches"]) == 2


@pytest.mark.anyio
async def test_duplicate_signup_rejected(client):
    body = {"name": "Dup Group", "owner_email": "dup@testgroup.ae", "password": "hunter2!"}
    first = await client.post("/api/v1/organizations/signup", json=body)
    assert first.status_code == 201
    second = await client.post("/api/v1/organizations/signup", json=body)
    assert second.status_code == 409
