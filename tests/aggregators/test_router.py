from datetime import date

import pytest


@pytest.mark.anyio
async def test_webhook_requires_api_key(client, auth_headers):
    resp = await client.post(
        "/api/v1/aggregators/talabat/webhook",
        json={"order_id": "X", "customer": {"phone": "+971500000910"}, "items": [], "total": "0.00"},
    )
    assert resp.status_code == 401


@pytest.mark.anyio
async def test_webhook_ingests_order_with_api_key(client, auth_headers):
    key_resp = await client.post(
        "/api/v1/api-keys", json={"label": "Talabat Integration"}, headers=auth_headers,
    )
    assert key_resp.status_code == 201
    api_key = key_resp.json()["api_key"]

    resp = await client.post(
        "/api/v1/aggregators/talabat/webhook",
        json={
            "order_id": "TB-555",
            "customer": {"phone": "+971500000911", "name": "Talabat Customer"},
            "items": [{"name": "Falafel Wrap", "quantity": 1, "price": "15.00"}],
            "total": "15.00",
        },
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 201
    assert "TB-555" in resp.json()["order_number"]


@pytest.mark.anyio
async def test_unsupported_provider_rejected(client, auth_headers):
    key_resp = await client.post(
        "/api/v1/api-keys", json={"label": "Bad Provider Key"}, headers=auth_headers,
    )
    api_key = key_resp.json()["api_key"]

    resp = await client.post(
        "/api/v1/aggregators/not-a-real-provider/webhook",
        json={"order_id": "X", "customer": {"phone": "+971500000912"}, "items": [], "total": "0.00"},
        headers={"X-API-Key": api_key},
    )
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_reconciliation_endpoint(client, auth_headers):
    key_resp = await client.post(
        "/api/v1/api-keys", json={"label": "Recon Key"}, headers=auth_headers,
    )
    api_key = key_resp.json()["api_key"]
    await client.post(
        "/api/v1/aggregators/deliveroo/webhook",
        json={
            "order_id": "DL-9", "customer": {"phone": "+971500000913", "name": "X"},
            "items": [{"name": "Pizza", "quantity": 1, "price": "30.00"}], "total": "30.00",
        },
        headers={"X-API-Key": api_key},
    )

    today = date.today().isoformat()
    resp = await client.get(
        f"/api/v1/aggregators/reconciliation?start_date={today}&end_date={today}", headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["deliveroo"]["order_count"] == 1
