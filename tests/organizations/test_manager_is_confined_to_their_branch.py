"""A branch manager runs ONE branch. The owner runs all of them.

The dashboard hides what a role may not open, but hiding is not a lock: a
manager's browser can be pointed at any URL, and a branch id is a small integer
anyone can guess. What actually confines them is the server, which is what this
file pins down — for the switch itself, not just for the listing.

test_router already covers /bootstrap and GET /branches. The gap was everything
that takes an id in the PATH: a caller who cannot LIST branches can still name
one, so "they can't see it" proves nothing about whether they can use it.
"""

import pytest

from app.identity.auth import create_access_token, hash_password
from app.staff.models import StaffMember


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


async def _branch(client, headers: dict, *, name: str) -> dict:
    resp = await client.post(
        "/api/v1/organizations/branches",
        json={"name": name, "lat": 25.2048, "lng": 55.2708},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _manager_at(db_session, restaurant_id: int, *, name: str) -> dict:
    """A manager signed in with a PIN at ONE branch."""
    manager = StaffMember(
        restaurant_id=restaurant_id,
        name=name,
        role="manager",
        pin_hash=hash_password("1286"),
        is_active=True,
    )
    db_session.add(manager)
    await db_session.commit()
    await db_session.refresh(manager)
    token = create_access_token(
        staff_id=manager.id, audience="staff", extra_claims={"role": "manager"}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_a_manager_cannot_switch_to_another_branch(client, db_session):
    """The switch is the whole boundary. Not being able to LIST branches proves
    nothing — this endpoint takes the id from the path, so a manager who simply
    guesses one would otherwise be handed a token for a branch that is not
    theirs."""
    hq = await _org_headers(client, name="Cafe Group", email="hq-mgr1@x.ae")
    mine = await _branch(client, hq, name="Marina")
    theirs = await _branch(client, hq, name="Deira")
    mgr = await _manager_at(db_session, mine["id"], name="Marina Manager")

    for target in (mine["id"], theirs["id"]):
        resp = await client.post(
            f"/api/v1/organizations/branches/{target}/session", headers=mgr
        )
        # 403, never 401: the manager IS authenticated, and a 401 would trip the
        # frontend auth interceptor and sign a working shift out mid-service.
        assert resp.status_code == 403, f"branch {target} answered {resp.status_code}"


@pytest.mark.anyio
async def test_a_manager_cannot_deactivate_a_branch(client, db_session):
    """Closing a location is an owner decision. A manager reaching this would be
    able to shut the branch next door — or their own, locking their staff out."""
    hq = await _org_headers(client, name="Cafe Group 2", email="hq-mgr2@x.ae")
    mine = await _branch(client, hq, name="Marina")
    theirs = await _branch(client, hq, name="Deira")
    mgr = await _manager_at(db_session, mine["id"], name="Marina Manager")

    for target in (mine["id"], theirs["id"]):
        resp = await client.patch(
            f"/api/v1/organizations/branches/{target}",
            json={"is_active": False},
            headers=mgr,
        )
        assert resp.status_code == 403, f"branch {target} answered {resp.status_code}"


@pytest.mark.anyio
async def test_a_manager_sees_only_their_own_branchs_staff(client, db_session):
    """Confinement is not just about branch endpoints. Every manager surface
    resolves its tenant from the manager's own staff row, so there is no id for
    them to tamper with — this proves that holds in practice."""
    hq = await _org_headers(client, name="Cafe Group 3", email="hq-mgr3@x.ae")
    mine = await _branch(client, hq, name="Marina")
    theirs = await _branch(client, hq, name="Deira")

    mgr = await _manager_at(db_session, mine["id"], name="Marina Manager")
    await _manager_at(db_session, theirs["id"], name="Deira Manager")

    listing = await client.get("/api/v1/staff", headers=mgr)
    assert listing.status_code == 200, listing.text
    names = {s["name"] for s in listing.json()}
    assert "Marina Manager" in names
    # The other branch's roster must not be visible, or "manages their branch
    # only" is a UI claim rather than a fact.
    assert "Deira Manager" not in names


@pytest.mark.anyio
async def test_staff_a_manager_creates_land_in_their_own_branch(client, db_session):
    """The tenant comes from the token, so a manager cannot plant a login in
    another branch even by asking."""
    hq = await _org_headers(client, name="Cafe Group 4", email="hq-mgr4@x.ae")
    mine = await _branch(client, hq, name="Marina")
    await _branch(client, hq, name="Deira")
    mgr = await _manager_at(db_session, mine["id"], name="Marina Manager")

    created = await client.post(
        "/api/v1/staff",
        json={"name": "New Waiter", "role": "waiter", "pin": "7731"},
        headers=mgr,
    )
    assert created.status_code == 201, created.text

    listing = await client.get("/api/v1/staff", headers=mgr)
    assert "New Waiter" in {s["name"] for s in listing.json()}


@pytest.mark.anyio
async def test_the_owner_can_still_do_all_of_it(client, db_session):
    """Positive control. Without this every assertion above passes just as well
    against endpoints that are broken for everybody."""
    hq = await _org_headers(client, name="Cafe Group 5", email="hq-mgr5@x.ae")
    a = await _branch(client, hq, name="Marina")
    b = await _branch(client, hq, name="Deira")

    for target in (a["id"], b["id"]):
        resp = await client.post(
            f"/api/v1/organizations/branches/{target}/session", headers=hq
        )
        assert resp.status_code == 200, resp.text

    # ...and the owner may close the non-main branch.
    closed = await client.patch(
        f"/api/v1/organizations/branches/{b['id']}",
        json={"is_active": False},
        headers=hq,
    )
    assert closed.status_code == 200, closed.text
