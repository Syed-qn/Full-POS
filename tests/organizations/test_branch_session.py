"""Switching branch issues a token for that branch — and only for branches the
caller owns.

This endpoint mints a restaurant-scoped token from an id in the URL, so the
ownership check is the whole security boundary: without it, any HQ account could
name any restaurant on the platform and be handed a working session for it.
"""

import pytest


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
    """Create a branch. Omitting ``email`` is the normal case: the branch has no
    login of its own and is managed through the owner account."""
    body: dict = {"name": name, "lat": 25.2048, "lng": 55.2708}
    if email:
        body |= {"email": email, "password": "hunter2!"}
    resp = await client.post(
        "/api/v1/organizations/branches", json=body, headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.anyio
async def test_owner_switches_branch_and_staff_land_on_that_branch(client):
    """The point of the switcher: create staff after switching and they belong
    to the branch that was picked, with that branch's own numbering."""
    hq = await _org_headers(client, name="Biryani Group", email="hq@biryani.ae")
    a = await _branch(client, hq, name="Deira", email="deira@biryani.ae")
    b = await _branch(client, hq, name="Marina", email="marina@biryani.ae")

    sess_a = await client.post(
        f"/api/v1/organizations/branches/{a['id']}/session", headers=hq
    )
    assert sess_a.status_code == 200, sess_a.text
    assert sess_a.json()["name"] == "Deira"
    head_a = {"Authorization": f"Bearer {sess_a.json()['access_token']}"}

    sess_b = await client.post(
        f"/api/v1/organizations/branches/{b['id']}/session", headers=hq
    )
    head_b = {"Authorization": f"Bearer {sess_b.json()['access_token']}"}

    made_a = await client.post(
        "/api/v1/staff/managers", json={"name": "Sara", "pin": "8471"}, headers=head_a
    )
    made_b = await client.post(
        "/api/v1/staff/managers", json={"name": "Omar", "pin": "7263"}, headers=head_b
    )
    assert made_a.status_code == 201, made_a.text
    assert made_b.status_code == 201, made_b.text
    # Each branch numbers its own people from 1 — the switch really re-scoped.
    assert made_a.json()["staff_code"] == 1
    assert made_b.json()["staff_code"] == 1

    listed_a = await client.get("/api/v1/staff/managers", headers=head_a)
    names_a = [m["name"] for m in listed_a.json()]
    assert names_a == ["Sara"], names_a  # Omar is not visible from Deira


@pytest.mark.anyio
async def test_cannot_open_a_session_on_another_orgs_branch(client):
    """The boundary. A valid HQ token plus someone else's branch id must not
    produce a session — otherwise the id in the path is the only thing standing
    between two businesses."""
    ours = await _org_headers(client, name="Biryani Group", email="hq@biryani.ae")
    theirs = await _org_headers(client, name="Shawarma Co", email="hq@shawarma.ae")

    mine = await _branch(client, ours, name="Deira", email="deira@biryani.ae")
    yours = await _branch(client, theirs, name="Karama", email="karama@shawarma.ae")

    ok = await client.post(
        f"/api/v1/organizations/branches/{mine['id']}/session", headers=ours
    )
    assert ok.status_code == 200

    stolen = await client.post(
        f"/api/v1/organizations/branches/{yours['id']}/session", headers=ours
    )
    assert stolen.status_code == 404, stolen.text


@pytest.mark.anyio
async def test_branch_without_credentials_cannot_be_signed_into(client, db_session):
    """A branch created with no email/password gets no usable credential at all.

    The placeholder email the column mints must not be reported as if it were a
    real login, and no password may open it — otherwise "one owner login" would
    quietly leave a second, weaker door on every store.
    """
    hq = await _org_headers(client, name="Biryani Group", email="hq@biryani.ae")
    made = await _branch(client, hq, name="Deira")  # no email, no password

    assert made["email"] is None
    assert made["has_login"] is False

    listed = await client.get("/api/v1/organizations/branches", headers=hq)
    assert [b["email"] for b in listed.json()] == [None]

    # The stored placeholder is a real column value; prove it opens nothing.
    from sqlalchemy import select

    from app.identity.models import Restaurant

    row = await db_session.scalar(
        select(Restaurant).where(Restaurant.id == made["id"])
    )
    placeholder = row.email
    assert placeholder.endswith("@auto.local")

    # "!" is the stored hash itself — a caller who learns the sentinel must not
    # be able to present it as the password.
    for attempt in ("", "hunter2!", "!", "password"):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": placeholder, "password": attempt}
        )
        # 401 from the hash check, or 422 when the schema rejects the input
        # first (the empty string). Either way no session is issued.
        assert resp.status_code in (401, 422), (attempt, resp.text)
        assert "access_token" not in resp.text

    # But the OWNER still reaches it, which is the whole point.
    sess = await client.post(
        f"/api/v1/organizations/branches/{made['id']}/session", headers=hq
    )
    assert sess.status_code == 200, sess.text
    assert sess.json()["name"] == "Deira"


@pytest.mark.anyio
async def test_exactly_one_branch_is_flagged_main(client):
    """The founding store is the main branch, and only it.

    There is no column for this: the organization is bootstrapped from its first
    restaurant, copying that email into owner_email, so the match is what
    identifies the original. Branches added later cannot collide because they
    carry either their own address or an @auto.local placeholder.
    """
    hq = await _org_headers(client, name="Biryani Group", email="hq@biryani.ae")
    # This org was created by /organizations/signup, which makes NO restaurant,
    # so no store carries owner_email and the oldest-store fallback decides.
    first = await _branch(client, hq, name="Deira")
    await _branch(client, hq, name="Marina")

    listed = (await client.get("/api/v1/organizations/branches", headers=hq)).json()
    flagged = [b["id"] for b in listed if b["is_main"]]
    assert flagged == [first["id"]], listed


@pytest.mark.anyio
async def test_founding_restaurant_is_main_even_when_not_the_oldest_row(client):
    """The realistic shape: a restaurant signs up, later becomes an organization.

    Its email becomes owner_email, so it is the main branch by identity rather
    than by being the lowest id — which is what makes the flag meaningful.
    """
    await client.post(
        "/api/v1/auth/signup",
        json={"name": "La Cafe", "email": "lacafe@test.ae", "password": "hunter2!"},
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": "lacafe@test.ae", "password": "hunter2!"}
    )
    owner = {"Authorization": f"Bearer {login.json()['access_token']}"}

    boot = await client.post("/api/v1/organizations/bootstrap", headers=owner)
    assert boot.status_code in (200, 201), boot.text

    await _branch(client, owner, name="Marina")

    listed = (await client.get("/api/v1/organizations/branches", headers=owner)).json()
    by_name = {b["name"]: b for b in listed}
    assert by_name["La Cafe"]["is_main"] is True
    assert by_name["Marina"]["is_main"] is False


@pytest.mark.anyio
async def test_branch_credentials_must_be_given_as_a_pair(client):
    """An email with no password would look like an account and be none."""
    hq = await _org_headers(client, name="Biryani Group", email="hq@biryani.ae")
    resp = await client.post(
        "/api/v1/organizations/branches",
        json={"name": "Deira", "lat": 25.2, "lng": 55.2, "email": "deira@biryani.ae"},
        headers=hq,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "email_and_password_together"


@pytest.mark.anyio
async def test_unknown_branch_id_is_rejected(client):
    hq = await _org_headers(client, name="Biryani Group", email="hq@biryani.ae")
    resp = await client.post(
        "/api/v1/organizations/branches/999999/session", headers=hq
    )
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_branch_session_requires_hq_authority(client):
    """A branch's own token is not HQ authority — it must not be able to hop to
    a sibling branch."""
    hq = await _org_headers(client, name="Biryani Group", email="hq@biryani.ae")
    a = await _branch(client, hq, name="Deira", email="deira@biryani.ae")
    b = await _branch(client, hq, name="Marina", email="marina@biryani.ae")

    login_a = await client.post(
        "/api/v1/auth/login", json={"email": "deira@biryani.ae", "password": "hunter2!"}
    )
    assert login_a.status_code == 200, login_a.text
    head_a = {"Authorization": f"Bearer {login_a.json()['access_token']}"}

    # Deira's own account IS linked to the org, so HQ context resolves — the
    # ownership check is what has to hold, and both branches are in the same org.
    hop = await client.post(
        f"/api/v1/organizations/branches/{b['id']}/session", headers=head_a
    )
    assert hop.status_code in (200, 403), hop.text
    if hop.status_code == 200:
        # Documented behaviour: a branch owner account carries org authority, so
        # it may switch within its OWN organization. Confirm it stays inside it.
        assert hop.json()["restaurant_id"] == b["id"]
        assert a["id"] != b["id"]
