"""Closing a branch without deleting it.

There is deliberately no delete endpoint: orders, staff, shifts and stock counts
all reference the restaurant row, and last month's sales at a branch really
happened. So a closed location is flagged, and the flag has to actually STOP
things — otherwise "deactivated" is decoration and the store keeps trading.
"""

import pytest

from tests.staff.test_rbac import store_key


async def _org_headers(client, *, name: str, email: str) -> dict:
    await client.post(
        "/api/v1/organizations/signup",
        json={"name": name, "owner_email": email, "password": "hunter2!"},
    )
    resp = await client.post(
        "/api/v1/organizations/login",
        json={"owner_email": email, "password": "hunter2!"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _branch(client, headers: dict, *, name: str, email: str | None = None) -> dict:
    body: dict = {"name": name, "lat": 25.2048, "lng": 55.2708}
    if email:
        body |= {"email": email, "password": "hunter2!"}
    resp = await client.post(
        "/api/v1/organizations/branches", json=body, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _second_branch(client, headers: dict, *, first: str, second: str) -> dict:
    """A branch that is NOT the main one.

    An org created through /signup has no founding restaurant, so main_branch_id
    falls back to the lowest id — which makes the FIRST branch created the de
    facto main, and main branches cannot be closed. Every closure test therefore
    needs two.
    """
    await _branch(client, headers, name=first)
    return await _branch(client, headers, name=second)


async def _find(client, headers: dict, branch_id: int) -> dict:
    listing = await client.get("/api/v1/organizations/branches", headers=headers)
    assert listing.status_code == 200, listing.text
    match = [b for b in listing.json() if b["id"] == branch_id]
    assert match, f"branch {branch_id} missing from listing"
    return match[0]


@pytest.mark.anyio
async def test_branches_start_open(client):
    """Positive control. Without it every assertion below passes just as well
    against a flag that is always False."""
    hq = await _org_headers(client, name="Group A", email="hq-a@x.ae")
    b = await _branch(client, hq, name="Marina")
    assert (await _find(client, hq, b["id"]))["is_active"] is True


@pytest.mark.anyio
async def test_deactivating_keeps_the_branch_listed(client):
    """Closed is not gone: the owner has to see it to reopen it."""
    hq = await _org_headers(client, name="Group B", email="hq-b@x.ae")
    b = await _second_branch(client, hq, first="Main St", second="Deira")

    resp = await client.patch(
        f"/api/v1/organizations/branches/{b['id']}",
        json={"is_active": False},
        headers=hq,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_active"] is False
    assert (await _find(client, hq, b["id"]))["is_active"] is False


@pytest.mark.anyio
async def test_a_closed_branch_will_not_open_a_session(client):
    """The real lock. Hiding it in the switcher stops nobody — this endpoint
    takes an id from the path and would otherwise hand back a working token."""
    hq = await _org_headers(client, name="Group C", email="hq-c@x.ae")
    b = await _second_branch(client, hq, first="Main St", second="JLT")

    ok = await client.post(
        f"/api/v1/organizations/branches/{b['id']}/session", headers=hq
    )
    assert ok.status_code == 200, ok.text

    await client.patch(
        f"/api/v1/organizations/branches/{b['id']}",
        json={"is_active": False},
        headers=hq,
    )
    denied = await client.post(
        f"/api/v1/organizations/branches/{b['id']}/session", headers=hq
    )
    # 409, not 404: the branch exists and may be reopened.
    assert denied.status_code == 409, denied.text


@pytest.mark.anyio
async def test_reopening_restores_the_session(client):
    """Deactivate must be reversible, or it is a delete with extra steps."""
    hq = await _org_headers(client, name="Group D", email="hq-d@x.ae")
    b = await _second_branch(client, hq, first="Main St", second="Barsha")

    await client.patch(
        f"/api/v1/organizations/branches/{b['id']}",
        json={"is_active": False},
        headers=hq,
    )
    await client.patch(
        f"/api/v1/organizations/branches/{b['id']}",
        json={"is_active": True},
        headers=hq,
    )
    resp = await client.post(
        f"/api/v1/organizations/branches/{b['id']}/session", headers=hq
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.anyio
async def test_the_main_branch_cannot_be_closed(client):
    """HQ authority derives from the founding restaurant. Closing it would leave
    nowhere to sign in and reopen it — locking the owner out of every branch."""
    hq = await _org_headers(client, name="Group E", email="hq-e@x.ae")
    await _branch(client, hq, name="Main St")
    await _branch(client, hq, name="Second")
    listing = await client.get("/api/v1/organizations/branches", headers=hq)
    main = [b for b in listing.json() if b["is_main"]]
    assert main, "expected the listing to nominate a main branch"

    resp = await client.patch(
        f"/api/v1/organizations/branches/{main[0]['id']}",
        json={"is_active": False},
        headers=hq,
    )
    assert resp.status_code == 409, resp.text
    assert (await _find(client, hq, main[0]["id"]))["is_active"] is True


@pytest.mark.anyio
async def test_another_orgs_branch_is_still_a_404_not_a_409(client):
    """The ownership check has to win over the new refusal, or this endpoint
    becomes a way to probe which restaurant ids exist."""
    mine = await _org_headers(client, name="Group F", email="hq-f@x.ae")
    theirs = await _org_headers(client, name="Group G", email="hq-g@x.ae")
    other = await _second_branch(client, theirs, first="Their Main", second="Not Mine")

    resp = await client.patch(
        f"/api/v1/organizations/branches/{other['id']}",
        json={"is_active": False},
        headers=mine,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.anyio
async def test_staff_cannot_sign_in_at_a_closed_branch(client, auth_headers, db_session):
    """A closed branch has no shifts. 401 with the same message as an unknown
    store, so this does not confirm to an outsider that the branch exists."""
    created = await client.post(
        "/api/v1/staff",
        json={"name": "Waiter Zed", "role": "waiter", "pin": "9182"},
        headers=auth_headers,
    )
    staff_id = created.json()["id"]
    store = await store_key(client, auth_headers)

    ok = await client.post(
        "/api/v1/staff/login",
        json={"store": store, "staff_id": staff_id, "pin": "9182"},
    )
    assert ok.status_code == 200, ok.text

    # Close the restaurant directly: this fixture's restaurant is standalone, so
    # it has no organization to PATCH through.
    from sqlalchemy import select

    from app.identity.models import Restaurant

    row = (await db_session.execute(select(Restaurant).limit(1))).scalars().first()
    row.is_active = False
    await db_session.commit()

    denied = await client.post(
        "/api/v1/staff/login",
        json={"store": store, "staff_id": staff_id, "pin": "9182"},
    )
    assert denied.status_code == 401, denied.text
