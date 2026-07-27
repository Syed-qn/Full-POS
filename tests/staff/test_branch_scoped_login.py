"""Staff sign-in must resolve inside ONE restaurant.

Regression cover for a cross-tenant login: staff numbers used to be the global
``staff_members.id`` and the login route looked them up with no restaurant
filter, so a manager at a brand-new restaurant who assumed they were "manager 1"
with PIN 1234 authenticated into whichever restaurant happened to own id 1.
"""

import pytest


async def _signup(client, *, name: str, email: str, phone: str) -> dict:
    await client.post(
        "/api/v1/auth/signup",
        json={
            "name": name, "email": email, "phone": phone,
            "password": "hunter2!", "lat": 25.2048, "lng": 55.2708,
        },
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": "hunter2!"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _store_code(client, headers: dict) -> str:
    resp = await client.get("/api/v1/staff/store-identity", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["store_code"]


async def _manager(client, headers: dict, *, name: str, pin: str) -> dict:
    resp = await client.post(
        "/api/v1/staff/managers", json={"name": name, "pin": pin}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.anyio
async def test_same_staff_number_and_pin_across_restaurants_stay_separate(
    client, auth_headers
):
    """R1, R2 (branch) and R3 (unrelated) each get their own "manager 1" / 8888."""
    r1 = auth_headers
    r2 = await _signup(
        client, name="Biryani House JLT", email="jlt@biryani.ae", phone="+971500000002"
    )
    r3 = await _signup(
        client, name="Shawarma Co", email="owner@shawarma.ae", phone="+971500000003"
    )

    m1 = await _manager(client, r1, name="Sara", pin="8462")
    m2 = await _manager(client, r2, name="Omar", pin="8462")
    m3 = await _manager(client, r3, name="Layla", pin="8462")

    # Each branch numbers its own staff from 1 — the surrogate ids differ.
    assert m1["staff_code"] == m2["staff_code"] == m3["staff_code"] == 1
    assert len({m1["id"], m2["id"], m3["id"]}) == 3

    codes = [await _store_code(client, h) for h in (r1, r2, r3)]
    assert len(set(codes)) == 3

    for store, expected in zip(codes, ("Sara", "Omar", "Layla")):
        login = await client.post(
            "/api/v1/staff/login",
            json={"store": store, "staff_code": 1, "pin": "8462"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["name"] == expected
        assert login.json()["staff_code"] == 1


@pytest.mark.anyio
async def test_staff_cannot_log_into_another_restaurant(client, auth_headers):
    """The original hole: R3's manager types number 1 + PIN 1234 and lands in R1."""
    r1 = auth_headers
    r3 = await _signup(
        client, name="Shawarma Co", email="owner@shawarma.ae", phone="+971500000003"
    )
    victim = await _manager(client, r1, name="Sara", pin="8471")
    await _manager(client, r3, name="Layla", pin="8471")

    r1_store = await _store_code(client, r1)
    r3_store = await _store_code(client, r3)

    # R3's own number resolved against R1's store must not authenticate, even
    # though the PIN is genuinely R1's manager's PIN too.
    stolen = await client.post(
        "/api/v1/staff/login",
        json={"store": r1_store, "staff_code": 1, "pin": "8471"},
    )
    assert stolen.status_code == 200  # this IS R1's own manager 1
    assert stolen.json()["name"] == "Sara"

    # The legacy surrogate id is now scoped too: R1's id presented at R3's store
    # is rejected outright.
    crossed = await client.post(
        "/api/v1/staff/login",
        json={"store": r3_store, "staff_id": victim["id"], "pin": "8471"},
    )
    assert crossed.status_code == 401, crossed.text


@pytest.mark.anyio
async def test_login_requires_a_store(client, auth_headers):
    await _manager(client, auth_headers, name="Sara", pin="8471")
    resp = await client.post("/api/v1/staff/login", json={"staff_code": 1, "pin": "8471"})
    assert resp.status_code == 422, resp.text


@pytest.mark.anyio
async def test_unknown_store_is_indistinguishable_from_a_bad_pin(client, auth_headers):
    await _manager(client, auth_headers, name="Sara", pin="8471")
    resp = await client.post(
        "/api/v1/staff/login",
        json={"store": "ZZZZZZZZ", "staff_code": 1, "pin": "8471"},
    )
    assert resp.status_code == 401
    assert "store" in resp.json()["detail"].lower()


@pytest.mark.anyio
async def test_staff_codes_increment_per_restaurant_and_survive_removal(
    client, auth_headers
):
    first = await _manager(client, auth_headers, name="Sara", pin="8471")
    second = await _manager(client, auth_headers, name="Omar", pin="7263")
    assert (first["staff_code"], second["staff_code"]) == (1, 2)

    await client.delete(f"/api/v1/staff/managers/{second['id']}", headers=auth_headers)
    third = await _manager(client, auth_headers, name="Huda", pin="5926")
    # 2 is retired, not recycled — reuse would re-point Omar's history onto Huda.
    assert third["staff_code"] == 3


@pytest.mark.anyio
@pytest.mark.parametrize("pin", ["1234", "0000", "1111", "4321", "123456"])
async def test_common_pins_are_rejected(client, auth_headers, pin):
    resp = await client.post(
        "/api/v1/staff/managers", json={"name": "Sara", "pin": pin}, headers=auth_headers
    )
    assert resp.status_code == 422, resp.text


@pytest.mark.anyio
async def test_duplicate_pin_rejected_within_a_restaurant_only(client, auth_headers):
    """Two managers sharing a PIN breaks approval attribution (approvals match by
    PIN alone). Across restaurants the same PIN is harmless and stays allowed."""
    await _manager(client, auth_headers, name="Sara", pin="8471")
    dupe = await client.post(
        "/api/v1/staff/managers", json={"name": "Omar", "pin": "8471"}, headers=auth_headers
    )
    assert dupe.status_code == 422, dupe.text

    other = await _signup(
        client, name="Shawarma Co", email="owner@shawarma.ae", phone="+971500000003"
    )
    elsewhere = await client.post(
        "/api/v1/staff/managers", json={"name": "Layla", "pin": "8471"}, headers=other
    )
    assert elsewhere.status_code == 201, elsewhere.text


@pytest.mark.anyio
async def test_store_identity_is_owner_only(client, auth_headers):
    from app.identity.auth import create_access_token

    mgr = await _manager(client, auth_headers, name="Sara", pin="8471")
    mgr_headers = {
        "Authorization": "Bearer "
        + create_access_token(
            staff_id=mgr["id"], audience="staff", extra_claims={"role": "manager"}
        )
    }
    resp = await client.get("/api/v1/staff/store-identity", headers=mgr_headers)
    assert resp.status_code == 403, resp.text
