from datetime import date

import pytest


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
        json={"name": "Branch A", "lat": 25.1, "lng": 55.1}, headers=headers,
    )
    assert branch1.status_code == 201
    branch2 = await client.post(
        "/api/v1/organizations/branches",
        json={"name": "Branch B", "lat": 25.2, "lng": 55.2}, headers=headers,
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
