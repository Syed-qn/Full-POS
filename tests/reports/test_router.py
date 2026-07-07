from datetime import date

import pytest


@pytest.mark.anyio
async def test_z_report_endpoint_returns_shape(client, auth_headers):
    today = date.today().isoformat()
    resp = await client.get(f"/api/v1/reports/z-report?target_date={today}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["date"] == today
    assert body["order_count"] == 0
    assert "drawer_sessions" in body
