"""The signed-in staff member's own live flags.

Login hands back training_mode once and the dashboard trusted that snapshot for
the whole shift, so a manager switching someone into training changed what the
SERVER stamped on the next order while the banner on their screen still said
the opposite. This endpoint is how the screen catches up.
"""
import pytest

from tests.staff.test_rbac import store_key


async def _waiter(client, auth_headers) -> tuple[int, dict[str, str]]:
    created = await client.post(
        "/api/v1/staff",
        json={"name": "Waiter Nadia", "role": "waiter", "pin": "5512"},
        headers=auth_headers,
    )
    staff_id = created.json()["id"]
    login = await client.post(
        "/api/v1/staff/login",
        json={
            "store": await store_key(client, auth_headers),
            "staff_id": staff_id,
            "pin": "5512",
        },
    )
    assert login.status_code == 200, login.text
    assert login.json()["training_mode"] is False
    return staff_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.mark.anyio
async def test_it_follows_a_change_made_mid_shift(client, auth_headers):
    staff_id, waiter = await _waiter(client, auth_headers)

    first = await client.get("/api/v1/staff/me", headers=waiter)
    assert first.status_code == 200, first.text
    assert first.json()["training_mode"] is False

    # Manager flips it while the waiter is still signed in on the floor.
    patched = await client.patch(
        f"/api/v1/staff/{staff_id}/training-mode",
        json={"training_mode": True},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text

    # Same token, no re-login — this is the whole point.
    again = await client.get("/api/v1/staff/me", headers=waiter)
    assert again.json()["training_mode"] is True
    assert again.json()["staff_id"] == staff_id
    assert again.json()["role"] == "waiter"


@pytest.mark.anyio
async def test_it_reads_only_your_own_row(client, auth_headers):
    """The id comes from the token, so there is no id to tamper with."""
    _, waiter = await _waiter(client, auth_headers)

    other = await client.post(
        "/api/v1/staff",
        json={"name": "Cashier Sam", "role": "cashier", "pin": "6613"},
        headers=auth_headers,
    )
    other_id = other.json()["id"]

    me = await client.get("/api/v1/staff/me", headers=waiter)
    assert me.json()["staff_id"] != other_id
    assert me.json()["name"] == "Waiter Nadia"


@pytest.mark.anyio
async def test_a_cashier_can_read_it_at_all(client, auth_headers):
    """It deliberately does NOT take current_restaurant, which 403s exactly the
    cashier and waiter tokens this exists for."""
    created = await client.post(
        "/api/v1/staff",
        json={"name": "Cashier Lee", "role": "cashier", "pin": "7714"},
        headers=auth_headers,
    )
    login = await client.post(
        "/api/v1/staff/login",
        json={
            "store": await store_key(client, auth_headers),
            "staff_id": created.json()["id"],
            "pin": "7714",
        },
    )
    cashier = {"Authorization": f"Bearer {login.json()['access_token']}"}

    resp = await client.get("/api/v1/staff/me", headers=cashier)
    assert resp.status_code == 200, resp.text
    assert resp.json()["role"] == "cashier"


@pytest.mark.anyio
async def test_an_owner_token_is_not_a_staff_member(client, auth_headers):
    """The owner account has no staff row, so there is nothing to return."""
    resp = await client.get("/api/v1/staff/me", headers=auth_headers)
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_a_deactivated_member_is_signed_out(client, auth_headers):
    """401, so the terminal drops the session rather than carrying on for
    somebody who no longer works here."""
    staff_id, waiter = await _waiter(client, auth_headers)

    await client.patch(
        f"/api/v1/staff/{staff_id}",
        json={"is_active": False},
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/staff/me", headers=waiter)
    assert resp.status_code == 401
