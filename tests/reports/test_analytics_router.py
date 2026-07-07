from datetime import date

import pytest


@pytest.mark.anyio
async def test_analytics_endpoints_return_empty_lists_with_no_data(client, auth_headers):
    today = date.today().isoformat()
    for path in ("item-performance", "inventory-usage", "table-turn-time"):
        resp = await client.get(
            f"/api/v1/reports/{path}?start_date={today}&end_date={today}", headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []

    labor = await client.get(f"/api/v1/reports/labor-hours?target_date={today}", headers=auth_headers)
    assert labor.status_code == 200
    assert labor.json() == []
