"""Marketing REST API router tests.

Uses the shared ``client`` + ``auth_headers`` fixtures from tests/conftest.py.
The marketing router must be wired into create_app() for these tests to pass.
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def test_create_segment(client, auth_headers):
    resp = await client.post(
        "/api/v1/marketing/segments",
        json={"name": "High Spenders", "dsl": {"all": [{"field": "total_spend", "op": "gte", "value": 100}]}},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "High Spenders"


async def test_list_segments_empty(client, auth_headers):
    resp = await client.get("/api/v1/marketing/segments", headers=auth_headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_create_template(client, auth_headers):
    resp = await client.post(
        "/api/v1/marketing/templates",
        json={
            "meta_template_name": "promo_test",
            "body": "Hello {{1}}, your exclusive deal awaits!",
            "language": "en",
            "category": "MARKETING",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["meta_template_name"] == "promo_test"


async def test_create_campaign_draft(client, auth_headers):
    resp = await client.post(
        "/api/v1/marketing/campaigns",
        json={"type": "promotional"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "draft"


async def test_list_campaigns_empty(client, auth_headers):
    resp = await client.get("/api/v1/marketing/campaigns", headers=auth_headers)
    assert resp.status_code == 200


async def test_campaign_stats(client, auth_headers):
    camp = (
        await client.post(
            "/api/v1/marketing/campaigns",
            json={"type": "promotional"},
            headers=auth_headers,
        )
    ).json()
    resp = await client.get(
        f"/api/v1/marketing/campaigns/{camp['id']}/stats",
        headers=auth_headers,
    )
    assert resp.status_code == 200
