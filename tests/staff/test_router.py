from datetime import date

import pytest


@pytest.mark.anyio
async def test_create_clock_in_out_and_query_hours(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Ahmed", "pin": "1234"}, headers=auth_headers,
    )
    assert resp.status_code == 201
    staff_id = resp.json()["id"]

    listing = await client.get("/api/v1/staff", headers=auth_headers)
    assert any(s["id"] == staff_id for s in listing.json())

    clock_in_resp = await client.post(
        f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers,
    )
    assert clock_in_resp.status_code == 200

    clock_out_resp = await client.post(
        f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_out"}, headers=auth_headers,
    )
    assert clock_out_resp.status_code == 200

    today = date.today().isoformat()
    hours = await client.get(
        f"/api/v1/staff/{staff_id}/hours?target_date={today}", headers=auth_headers,
    )
    assert hours.status_code == 200
    assert "hours" in hours.json()

    sales = await client.get(
        f"/api/v1/staff/{staff_id}/sales?target_date={today}", headers=auth_headers,
    )
    assert sales.status_code == 200
    assert sales.json()["sales_aed"] == "0.00"


@pytest.mark.anyio
async def test_double_clock_in_returns_409(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Bilal", "pin": "5678"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers)
    second = await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers)
    assert second.status_code == 409


@pytest.mark.anyio
async def test_hours_endpoint_reports_overtime(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Fatima", "pin": "9999"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]

    clock_start = await client.post(
        f"/api/v1/staff/{staff_id}/clock", json={"type": "break_start"}, headers=auth_headers,
    )
    assert clock_start.status_code == 409  # not clocked in yet


@pytest.mark.anyio
async def test_break_start_and_end_via_router(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Karim", "pin": "1111"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers)
    start = await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "break_start"}, headers=auth_headers)
    assert start.status_code == 200
    end = await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "break_end"}, headers=auth_headers)
    assert end.status_code == 200
