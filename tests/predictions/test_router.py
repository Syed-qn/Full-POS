"""Router tests for the predictions endpoints.

Uses the ``client`` / ``auth_headers`` fixtures from tests/conftest.py.
The predictions router is mounted by the local conftest override.
"""
import pytest

pytestmark = pytest.mark.asyncio


async def test_get_latest_forecast_empty(client, auth_headers):
    """No forecast yet — should return 404 or empty list."""
    resp = await client.get(
        "/api/v1/predictions/latest?horizon=lunch",
        headers=auth_headers,
    )
    assert resp.status_code in (200, 404)


async def test_list_forecast_runs_empty(client, auth_headers):
    resp = await client.get("/api/v1/predictions/runs", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json() == []


async def test_create_override(client, auth_headers):
    resp = await client.post(
        "/api/v1/predictions/overrides",
        json={"raw_text": "Increase Friday dinner demand by 20%"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "id" in body
    assert "parsed_effect" in body


async def test_prep_ahead_empty(client, auth_headers):
    resp = await client.get(
        "/api/v1/predictions/prep-ahead?horizon=lunch",
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
