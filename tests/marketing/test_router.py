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


async def test_delete_template_removes_it_from_the_list(client, auth_headers):
    created = await client.post(
        "/api/v1/marketing/templates",
        json={
            "meta_template_name": "promo_to_delete",
            "body": "Hi {{1}}, your exclusive deal awaits today!",
            "language": "en",
            "category": "MARKETING",
        },
        headers=auth_headers,
    )
    tid = created.json()["id"]
    before = await client.get("/api/v1/marketing/templates", headers=auth_headers)
    assert any(t["id"] == tid for t in before.json())

    resp = await client.delete(f"/api/v1/marketing/templates/{tid}", headers=auth_headers)
    assert resp.status_code == 204

    after = await client.get("/api/v1/marketing/templates", headers=auth_headers)
    assert all(t["id"] != tid for t in after.json())


async def test_list_templates_includes_content_for_preview(client, auth_headers):
    body = "Hi {{1}}, today's grill mandhi special is ready — order now!"
    await client.post(
        "/api/v1/marketing/templates",
        json={
            "meta_template_name": "promo_preview_me",
            "body": body,
            "footer": "Reply STOP to opt out",
            "language": "en",
            "category": "MARKETING",
        },
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/marketing/templates", headers=auth_headers)
    row = next(t for t in resp.json() if t["meta_template_name"] == "promo_preview_me")
    assert row["body"] == body
    assert row["footer"] == "Reply STOP to opt out"


async def test_delete_template_unknown_returns_404(client, auth_headers):
    resp = await client.delete("/api/v1/marketing/templates/999999", headers=auth_headers)
    assert resp.status_code == 404


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


async def test_template_image_persists_in_db_and_serves_via_media(client, auth_headers):
    """Header image bytes are stored in Postgres and served back via /media, so
    they survive redeploys instead of vanishing with the ephemeral local disk."""
    png = b"\x89PNG\r\n\x1a\n" + b"fake-png-payload"
    up = await client.post(
        "/api/v1/marketing/templates/image",
        files={"file": ("promo.png", png, "image/png")},
        headers=auth_headers,
    )
    assert up.status_code == 200
    url = up.json()["url"]
    assert "/media/marketing/" in url
    rel = url.split("/media/", 1)[1]
    # Served back through the DB-backed media route (public, no auth needed).
    got = await client.get(f"/media/{rel}")
    assert got.status_code == 200
    assert got.headers["content-type"].startswith("image/png")
    assert got.content == png


async def test_media_unknown_path_returns_404(client):
    resp = await client.get("/media/marketing/1/nope-does-not-exist.png")
    assert resp.status_code == 404


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


async def test_list_campaigns_includes_template_and_audience_labels(client, auth_headers):
    """Enriched list rows expose template name, audience label, and timestamps."""
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "camp_label_tpl",
                "body": "Hi {{1}}, weekend deal!",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()
    seg = (
        await client.post(
            "/api/v1/marketing/segments",
            json={
                "name": "VIP Lunch",
                "dsl": {"all": [{"field": "order_count", "op": "gte", "value": 3}]},
            },
            headers=auth_headers,
        )
    ).json()
    await client.post(
        "/api/v1/marketing/campaigns",
        json={"type": "promotional", "template_id": tpl["id"], "segment_id": seg["id"]},
        headers=auth_headers,
    )
    resp = await client.get("/api/v1/marketing/campaigns", headers=auth_headers)
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["template_id"] == tpl["id"])
    assert row["template_name"] == "camp_label_tpl"
    assert row["audience_label"] == "VIP Lunch"
    assert row["segment_id"] == seg["id"]
    assert row["created_at"] is not None


async def test_broadcast_persists_rfm_segment_in_stats(client, auth_headers):
    """RFM bucket choice is stored on the campaign so historical rows stay labelable."""
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "rfm_persist_tpl",
                "body": "Hi {{1}}, champions offer!",
                "footer": "Reply STOP to opt out",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
    )
    bc = await client.post(
        "/api/v1/marketing/broadcast",
        json={"template_id": tpl["id"], "type": "promotional", "rfm_segment": "champions"},
        headers=auth_headers,
    )
    assert bc.status_code == 201
    listed = await client.get("/api/v1/marketing/campaigns", headers=auth_headers)
    row = next(r for r in listed.json() if r["id"] == bc.json()["campaign_id"])
    assert row["stats"]["rfm_segment"] == "champions"
    assert row["audience_label"] == "Champions"


async def test_compile_segment_returns_dsl_and_count(client, auth_headers):
    resp = await client.post(
        "/api/v1/marketing/segments/compile",
        json={"plain_english": "customers who spent over AED 200"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "dsl" in data
    assert data["preview_count"] >= 0
    assert data["plain_english"] == "customers who spent over AED 200"


async def test_compile_segment_rejects_invalid_dsl_from_compiler(
    client, auth_headers, monkeypatch
):
    class _BadCompiler:
        def compile(self, text: str) -> dict:
            return {"all": [{"field": "DROP", "op": "eq", "value": 1}]}

    monkeypatch.setattr(
        "app.llm.factory.get_segment_compiler", lambda: _BadCompiler()
    )
    resp = await client.post(
        "/api/v1/marketing/segments/compile",
        json={"plain_english": "customers who spent over AED 200"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "simplifying" in resp.json()["detail"].lower()


async def test_preview_segment_validates_dsl(client, auth_headers):
    resp = await client.post(
        "/api/v1/marketing/segments/preview",
        json={"dsl": {"all": [{"field": "order_count", "op": "gte", "value": 1}]}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert "preview_count" in resp.json()


async def test_delete_segment_not_found(client, auth_headers):
    resp = await client.delete(
        "/api/v1/marketing/segments/999999", headers=auth_headers
    )
    assert resp.status_code == 404


async def test_delete_segment_success(client, auth_headers):
    created = await client.post(
        "/api/v1/marketing/segments",
        json={
            "name": "To delete",
            "dsl": {"all": [{"field": "order_count", "op": "gte", "value": 1}]},
        },
        headers=auth_headers,
    )
    sid = created.json()["id"]
    resp = await client.delete(
        f"/api/v1/marketing/segments/{sid}", headers=auth_headers
    )
    assert resp.status_code == 204
    listed = await client.get("/api/v1/marketing/segments", headers=auth_headers)
    assert all(s["id"] != sid for s in listed.json())


async def test_broadcast_rejects_segment_and_rfm_together(client, auth_headers):
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "mutual_tpl",
                "body": "Hi {{1}}, deal!",
                "footer": "Reply STOP to opt out",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
    )
    seg = (
        await client.post(
            "/api/v1/marketing/segments",
            json={
                "name": "VIP",
                "dsl": {"all": [{"field": "order_count", "op": "gte", "value": 1}]},
            },
            headers=auth_headers,
        )
    ).json()
    resp = await client.post(
        "/api/v1/marketing/broadcast",
        json={
            "template_id": tpl["id"],
            "segment_id": seg["id"],
            "rfm_segment": "champions",
            "type": "promotional",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "not both" in resp.json()["detail"].lower()


async def test_broadcast_with_segment_id_targets_subset(
    client, db_session, auth_headers
):
    from decimal import Decimal

    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer

    rest = (await db_session.execute(select(Restaurant).limit(1))).scalar_one()
    db_session.add_all(
        [
            Customer(
                restaurant_id=rest.id,
                phone="+971500000201",
                name="Big",
                total_orders=5,
                total_spend=Decimal("300"),
            ),
            Customer(
                restaurant_id=rest.id,
                phone="+971500000202",
                name="Small",
                total_orders=1,
                total_spend=Decimal("40"),
            ),
        ]
    )
    await db_session.flush()

    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "seg_target_tpl",
                "body": "Hi {{1}}, offer!",
                "footer": "Reply STOP to opt out",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
    )
    seg = (
        await client.post(
            "/api/v1/marketing/segments",
            json={
                "name": "High spenders",
                "dsl": {"all": [{"field": "total_spend", "op": "gte", "value": 200}]},
            },
            headers=auth_headers,
        )
    ).json()
    bc = await client.post(
        "/api/v1/marketing/broadcast",
        json={
            "template_id": tpl["id"],
            "segment_id": seg["id"],
            "type": "promotional",
        },
        headers=auth_headers,
    )
    assert bc.status_code == 201
    assert bc.json()["queued"] == 1


async def test_broadcast_with_coupon_value_issues_codes(
    client, db_session, auth_headers
):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order
    from app.outbox.models import OutboxMessage

    rest = (await db_session.execute(select(Restaurant).limit(1))).scalar_one()
    cust = Customer(
        restaurant_id=rest.id, phone="+971500000301", name="Coupon Cust"
    )
    db_session.add(cust)
    await db_session.flush()
    db_session.add(
        Order(
            restaurant_id=rest.id,
            customer_id=cust.id,
            order_number="R1-COUPON",
            status="delivered",
        )
    )
    await db_session.flush()

    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "coupon_tpl",
                "body": "Hi {{1}}, use code {{2}} on your next order!",
                "footer": "Reply STOP to opt out",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
    )
    bc = await client.post(
        "/api/v1/marketing/broadcast",
        json={
            "template_id": tpl["id"],
            "type": "promotional",
            "coupon_value": "10.00",
        },
        headers=auth_headers,
    )
    assert bc.status_code == 201
    assert bc.json()["queued"] == 1
    row = (
        await db_session.execute(
            select(OutboxMessage).where(OutboxMessage.restaurant_id == rest.id)
        )
    ).scalar_one()
    assert "SORRY-" in str(row.payload)


async def test_broadcast_coupon_skipped_when_no_order(client, db_session, auth_headers):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer

    rest = (await db_session.execute(select(Restaurant).limit(1))).scalar_one()
    db_session.add(
        Customer(
            restaurant_id=rest.id, phone="+971500000401", name="No Order"
        )
    )
    await db_session.flush()

    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "coupon_skip_tpl",
                "body": "Hi {{1}}, enjoy our offer today!",
                "footer": "Reply STOP to opt out",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
    )
    bc = await client.post(
        "/api/v1/marketing/broadcast",
        json={
            "template_id": tpl["id"],
            "type": "promotional",
            "coupon_value": "5.00",
        },
        headers=auth_headers,
    )
    assert bc.status_code == 201
    assert bc.json()["queued"] == 1


async def test_create_template_ephemeral_flag_persisted(
    client, db_session, auth_headers
):
    from app.marketing.models import WaTemplate

    resp = await client.post(
        "/api/v1/marketing/templates",
        json={
            "meta_template_name": "ephemeral_daily",
            "body": "Hi {{1}}, today's special is ready — order now!",
            "footer": "Reply STOP to opt out",
            "language": "en",
            "category": "MARKETING",
            "ephemeral": True,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    tpl = await db_session.get(WaTemplate, resp.json()["id"])
    assert tpl is not None
    assert tpl.ephemeral is True


async def test_fix_template_rejected_returns_revised_body_and_sets_draft(
    client, db_session, auth_headers
):
    from app.marketing.models import WaTemplate

    created = await client.post(
        "/api/v1/marketing/templates",
        json={
            "meta_template_name": "fix_me_tpl",
            "body": "Hi {{1}}, check https://bad.example/deal today!",
            "footer": "Reply STOP to opt out",
            "language": "en",
            "category": "MARKETING",
        },
        headers=auth_headers,
    )
    tpl = await db_session.get(WaTemplate, created.json()["id"])
    tpl.status = "rejected"
    tpl.rejection_reason = "URLs are not allowed in the body"
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/marketing/templates/{tpl.id}/fix",
        json={"hint": "remove the link"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "draft"
    assert data["rejection_reason"] is None
    assert "https://" not in data["body"]


async def test_fix_template_fails_lint_returns_422(
    client, db_session, auth_headers, monkeypatch
):
    from app.marketing.models import WaTemplate

    async def _bad_fix(**_kwargs):
        return {
            "body": "Hi {{1}}, still bad http://evil.example",
            "footer": "Reply STOP to opt out",
        }

    monkeypatch.setattr("app.marketing.service.fix_template_body", _bad_fix)

    created = await client.post(
        "/api/v1/marketing/templates",
        json={
            "meta_template_name": "lint_fail_tpl",
            "body": "Hi {{1}}, visit https://bad.example now!",
            "footer": "Reply STOP to opt out",
            "language": "en",
            "category": "MARKETING",
        },
        headers=auth_headers,
    )
    tpl = await db_session.get(WaTemplate, created.json()["id"])
    tpl.status = "rejected"
    tpl.rejection_reason = "URLs not allowed"
    await db_session.flush()

    resp = await client.post(
        f"/api/v1/marketing/templates/{tpl.id}/fix",
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_fix_template_rejects_non_rejected(client, auth_headers):
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "approved_fix",
                "body": "Hi {{1}}, deal!",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()
    resp = await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/fix",
        headers=auth_headers,
    )
    assert resp.status_code == 422


async def test_resubmit_after_fix_approves(client, db_session, auth_headers):
    from app.marketing.models import WaTemplate

    created = await client.post(
        "/api/v1/marketing/templates",
        json={
            "meta_template_name": "resubmit_fix_tpl",
            "body": "Hi {{1}}, visit https://bad.example now!",
            "footer": "Reply STOP to opt out",
            "language": "en",
            "category": "MARKETING",
        },
        headers=auth_headers,
    )
    tpl = await db_session.get(WaTemplate, created.json()["id"])
    tpl.status = "rejected"
    tpl.rejection_reason = "URLs not allowed"
    await db_session.flush()

    await client.post(
        f"/api/v1/marketing/templates/{tpl.id}/fix", headers=auth_headers
    )
    submitted = await client.post(
        f"/api/v1/marketing/templates/{tpl.id}/submit", headers=auth_headers
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "approved"


async def test_broadcast_rejects_invalid_coupon_value(client, auth_headers):
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "bad_coupon_tpl",
                "body": "Hi {{1}}, deal!",
                "footer": "Reply STOP to opt out",
                "language": "en",
                "category": "MARKETING",
            },
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
    )
    resp = await client.post(
        "/api/v1/marketing/broadcast",
        json={
            "template_id": tpl["id"],
            "type": "promotional",
            "coupon_value": "not-a-number",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
