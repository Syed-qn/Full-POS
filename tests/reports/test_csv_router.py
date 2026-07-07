from datetime import date

import pytest


@pytest.mark.anyio
async def test_item_performance_csv_endpoint(client, auth_headers):
    today = date.today().isoformat()
    resp = await client.get(
        f"/api/v1/reports/item-performance.csv?start_date={today}&end_date={today}", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
