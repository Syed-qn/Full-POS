import pytest


@pytest.mark.anyio
async def test_open_add_event_close_lifecycle(client, auth_headers):
    open_resp = await client.post(
        "/api/v1/cash-drawer/sessions", json={"opening_float_aed": "200.00"}, headers=auth_headers,
    )
    assert open_resp.status_code == 201
    session_id = open_resp.json()["id"]
    assert open_resp.json()["status"] == "open"

    current = await client.get("/api/v1/cash-drawer/sessions/current", headers=auth_headers)
    assert current.status_code == 200
    assert current.json()["id"] == session_id

    ev = await client.post(
        f"/api/v1/cash-drawer/sessions/{session_id}/events",
        json={"type": "cash_in", "amount_aed": "500.00", "reason": "rider handover"},
        headers=auth_headers,
    )
    assert ev.status_code == 201

    close = await client.post(
        f"/api/v1/cash-drawer/sessions/{session_id}/close",
        json={"closing_count_aed": "700.00"},
        headers=auth_headers,
    )
    assert close.status_code == 200
    assert close.json()["status"] == "closed"
    assert close.json()["variance_aed"] == "0.00"


@pytest.mark.anyio
async def test_double_open_rejected(client, auth_headers):
    resp1 = await client.post(
        "/api/v1/cash-drawer/sessions", json={"opening_float_aed": "200.00"}, headers=auth_headers,
    )
    assert resp1.status_code == 201
    resp2 = await client.post(
        "/api/v1/cash-drawer/sessions", json={"opening_float_aed": "100.00"}, headers=auth_headers,
    )
    assert resp2.status_code == 409


@pytest.mark.anyio
async def test_current_session_404_when_none_open(client, auth_headers):
    resp = await client.get("/api/v1/cash-drawer/sessions/current", headers=auth_headers)
    assert resp.status_code == 404
