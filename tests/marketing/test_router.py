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


async def test_create_template_duplicate_name_auto_suffixes(client, auth_headers):
    """Re-drafting the same offer (same suggested name) must NOT 500 on the unique
    (restaurant, name, language) constraint — the draft name auto-suffixes instead."""
    payload = {
        "meta_template_name": "promo_dup",
        "body": "Hi {{1}}, deal!",
        "language": "en",
        "category": "MARKETING",
    }
    first = await client.post("/api/v1/marketing/templates", json=payload, headers=auth_headers)
    assert first.status_code == 201
    assert first.json()["meta_template_name"] == "promo_dup"

    second = await client.post("/api/v1/marketing/templates", json=payload, headers=auth_headers)
    assert second.status_code == 201
    assert second.json()["meta_template_name"] == "promo_dup_2"

    third = await client.post("/api/v1/marketing/templates", json=payload, headers=auth_headers)
    assert third.status_code == 201
    assert third.json()["meta_template_name"] == "promo_dup_3"


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


async def test_submit_image_template_without_app_id_gives_clear_error(client, auth_headers, monkeypatch):
    """An IMAGE-header template submitted to real Meta with no APP_WA_APP_ID must
    return a clear 422 (not a 500) telling the manager to set the App ID."""
    from app.config import get_settings

    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "img_promo",
                "body": "Hi {{1}}, big offer today! Reply to order.",
                "footer": "Reply STOP to opt out",
                "header": {"type": "IMAGE", "image_url": "https://example.com/x.jpg"},
            },
            headers=auth_headers,
        )
    ).json()

    monkeypatch.setenv("APP_MARKETING_SEND_DRY_RUN", "false")
    monkeypatch.setenv("APP_MARKETING_TEMPLATE_PROVIDER", "meta")
    monkeypatch.setenv("APP_WA_APP_ID", "")
    get_settings.cache_clear()
    try:
        resp = await client.post(
            f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
        )
        assert resp.status_code == 422
        assert "APP_WA_APP_ID" in resp.json()["detail"]
    finally:
        get_settings.cache_clear()


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
