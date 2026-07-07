import pytest


@pytest.mark.anyio
async def test_staff_login_returns_token_with_role(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Manager Ali", "role": "manager", "pin": "9999"},
        headers=auth_headers,
    )
    staff_id = resp.json()["id"]

    login = await client.post(
        "/api/v1/staff/login", json={"staff_id": staff_id, "pin": "9999"},
    )
    assert login.status_code == 200
    assert "access_token" in login.json()


@pytest.mark.anyio
async def test_staff_login_wrong_pin_rejected(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Cook Sam", "role": "kitchen", "pin": "1111"},
        headers=auth_headers,
    )
    staff_id = resp.json()["id"]

    login = await client.post(
        "/api/v1/staff/login", json={"staff_id": staff_id, "pin": "0000"},
    )
    assert login.status_code == 401


@pytest.mark.anyio
async def test_manager_only_endpoint_rejects_non_manager_staff(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Cook Amina", "role": "kitchen", "pin": "2222"},
        headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    login = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "2222"})
    staff_token = login.json()["access_token"]
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    # cash drawer open requires the "manager" role
    resp2 = await client.post(
        "/api/v1/cash-drawer/sessions", json={"opening_float_aed": "200.00"}, headers=staff_headers,
    )
    assert resp2.status_code == 403


@pytest.mark.anyio
async def test_manager_only_endpoint_allows_manager_role_staff(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Manager Zaid", "role": "manager", "pin": "3333"},
        headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    login = await client.post("/api/v1/staff/login", json={"staff_id": staff_id, "pin": "3333"})
    staff_token = login.json()["access_token"]
    staff_headers = {"Authorization": f"Bearer {staff_token}"}

    resp2 = await client.post(
        "/api/v1/cash-drawer/sessions", json={"opening_float_aed": "150.00"}, headers=staff_headers,
    )
    assert resp2.status_code == 201


@pytest.mark.anyio
async def test_owner_manager_token_still_works_on_manager_only_endpoint(client, auth_headers):
    # the original restaurant-owner login (no staff record at all) must still work —
    # RBAC is additive, not a breaking change to the existing manager auth path.
    resp = await client.post(
        "/api/v1/cash-drawer/sessions", json={"opening_float_aed": "100.00"}, headers=auth_headers,
    )
    assert resp.status_code == 201
