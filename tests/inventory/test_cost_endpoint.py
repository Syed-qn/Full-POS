import pytest


@pytest.mark.anyio
async def test_update_cost_endpoint(client, auth_headers):
    resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Rice", "unit": "kg", "current_stock": "5.000", "low_stock_threshold": "1.000"},
        headers=auth_headers,
    )
    ing_id = resp.json()["id"]

    cost_resp = await client.patch(
        f"/api/v1/ingredients/{ing_id}/cost", json={"cost_per_unit_aed": "3.5000"}, headers=auth_headers,
    )
    assert cost_resp.status_code == 200
    assert cost_resp.json()["cost_per_unit_aed"] == "3.5000"
