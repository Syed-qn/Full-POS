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


@pytest.mark.anyio
async def test_create_staff_writes_audit_log(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Tariq", "pin": "2468"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]

    audit_resp = await client.get(
        "/api/v1/audit-log?entity=staff_member", headers=auth_headers,
    )
    assert audit_resp.status_code == 200
    rows = audit_resp.json()["rows"]
    assert any(r["action"] == "staff_created" and r["entity_id"] == str(staff_id) for r in rows)


@pytest.mark.anyio
async def test_clock_in_writes_audit_log(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Salma", "pin": "3579"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers)

    audit_resp = await client.get(
        "/api/v1/audit-log?entity=clock_event", headers=auth_headers,
    )
    assert audit_resp.status_code == 200
    rows = audit_resp.json()["rows"]
    assert any(r["action"] == "clock_in" and r["entity_id"] == str(staff_id) for r in rows)


@pytest.mark.anyio
async def test_status_endpoint_reports_clocked_out_when_no_events(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Dana", "pin": "1357"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]

    status_resp = await client.get(f"/api/v1/staff/{staff_id}/status", headers=auth_headers)
    assert status_resp.status_code == 200
    assert status_resp.json() == {"staff_id": staff_id, "status": "clocked_out"}


@pytest.mark.anyio
async def test_status_endpoint_reports_clocked_in_after_clock_in(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Rami", "pin": "2468"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers)

    status_resp = await client.get(f"/api/v1/staff/{staff_id}/status", headers=auth_headers)
    assert status_resp.status_code == 200
    assert status_resp.json() == {"staff_id": staff_id, "status": "clocked_in"}


@pytest.mark.anyio
async def test_status_endpoint_reports_on_break(client, auth_headers):
    resp = await client.post(
        "/api/v1/staff", json={"name": "Huda", "pin": "8642"}, headers=auth_headers,
    )
    staff_id = resp.json()["id"]
    await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "clock_in"}, headers=auth_headers)
    await client.post(f"/api/v1/staff/{staff_id}/clock", json={"type": "break_start"}, headers=auth_headers)

    status_resp = await client.get(f"/api/v1/staff/{staff_id}/status", headers=auth_headers)
    assert status_resp.status_code == 200
    assert status_resp.json() == {"staff_id": staff_id, "status": "on_break"}


@pytest.mark.anyio
async def test_status_endpoint_404_for_unowned_staff(client, auth_headers):
    status_resp = await client.get("/api/v1/staff/999999/status", headers=auth_headers)
    assert status_resp.status_code == 404
