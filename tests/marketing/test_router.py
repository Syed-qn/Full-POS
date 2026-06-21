"""Marketing REST API router tests.

Uses the shared ``client`` + ``auth_headers`` fixtures from tests/conftest.py.
The marketing router must be wired into create_app() for these tests to pass.
"""
import pytest

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


async def test_template_draft_endpoint(client, auth_headers):
    """AI-draft returns a usable body with the {{1}} name placeholder."""
    resp = await client.post(
        "/api/v1/marketing/templates/draft",
        json={"describe": "20% off all biryani this weekend"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "{{1}}" in data["body"]
    assert data["suggested_name"]


async def test_template_image_rejects_non_image(client, auth_headers):
    resp = await client.post(
        "/api/v1/marketing/templates/image",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_submit_then_broadcast_flow(client, auth_headers):
    """Create → submit (mock provider approves a compliant template) → broadcast."""
    # A compliant body: greeting + single placeholder + STOP opt-out in footer.
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "weekend_promo",
                "body": "Hi {{1}}, enjoy 20% off all biryani this weekend. Reply to order!",
                "footer": "Reply STOP to opt out",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()

    submitted = await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "approved"  # mock provider auto-approves compliant

    bc = await client.post(
        "/api/v1/marketing/broadcast",
        json={"template_id": tpl["id"], "type": "promotional"},
        headers=auth_headers,
    )
    assert bc.status_code == 201
    body = bc.json()
    assert "campaign_id" in body
    # No opted-in customers seeded → 0 queued, but the flow completes cleanly.
    assert body["queued"] >= 0


async def test_broadcast_rejects_unapproved_template(client, auth_headers):
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={"meta_template_name": "draft_only", "body": "Hi {{1}}, deal!", "language": "en"},
            headers=auth_headers,
        )
    ).json()
    resp = await client.post(
        "/api/v1/marketing/broadcast",
        json={"template_id": tpl["id"], "type": "promotional"},
        headers=auth_headers,
    )
    assert resp.status_code == 422  # template not approved


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
