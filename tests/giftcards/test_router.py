import pytest


@pytest.mark.anyio
async def test_purchase_and_check_balance(client, auth_headers):
    resp = await client.post(
        "/api/v1/gift-cards/purchase",
        json={"recipient_phone": "+971500000077", "amount_aed": "75.00", "purchase_reference": "GCR-0001"},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    balance = await client.get("/api/v1/gift-cards/balance/+971500000077", headers=auth_headers)
    assert balance.status_code == 200
    assert balance.json()["balance_aed"] == "75.00"
