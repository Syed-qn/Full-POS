import pytest


@pytest.mark.anyio
async def test_create_list_and_low_stock(client, auth_headers):
    resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Rice", "unit": "kg", "current_stock": "2.000", "low_stock_threshold": "5.000"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    ing_id = resp.json()["id"]

    listing = await client.get("/api/v1/ingredients", headers=auth_headers)
    assert listing.status_code == 200
    assert any(i["id"] == ing_id for i in listing.json())

    low = await client.get("/api/v1/ingredients/low-stock", headers=auth_headers)
    assert low.status_code == 200
    assert any(i["id"] == ing_id for i in low.json())


@pytest.mark.anyio
async def test_restock_and_waste(client, auth_headers):
    resp = await client.post(
        "/api/v1/ingredients",
        json={"name": "Onion", "unit": "kg", "current_stock": "10.000", "low_stock_threshold": "1.000"},
        headers=auth_headers,
    )
    ing_id = resp.json()["id"]

    restocked = await client.post(
        f"/api/v1/ingredients/{ing_id}/restock", json={"quantity": "5.000"}, headers=auth_headers,
    )
    assert restocked.status_code == 200
    assert restocked.json()["current_stock"] == "15.000"

    wasted = await client.post(
        f"/api/v1/ingredients/{ing_id}/waste", json={"quantity": "2.000", "reason": "spoiled"},
        headers=auth_headers,
    )
    assert wasted.status_code == 200
    assert wasted.json()["current_stock"] == "13.000"
