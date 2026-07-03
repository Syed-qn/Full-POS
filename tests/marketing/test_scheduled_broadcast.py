"""Phase 5 — scheduled broadcast, cancel, reschedule."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.marketing.models import Campaign, MarketingSend, WaTemplate
from app.marketing.worker import _dispatch_scheduled
from app.ordering.models import Customer

pytestmark = pytest.mark.asyncio


def _make_session_factory(session):
    @asynccontextmanager
    async def _factory():
        yield session

    return _factory


async def _approved_tpl(client, auth_headers, name: str = "sched_promo"):
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": name,
                "body": "Hi {{1}}, enjoy our weekend biryani deal! Reply to order.",
                "footer": "Reply STOP to opt out",
            },
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/api/v1/marketing/templates/{tpl['id']}/submit", headers=auth_headers
    )
    return tpl


def _future(minutes: int = 30) -> str:
    t = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    return t.isoformat().replace("+00:00", "Z")


async def test_broadcast_scheduled_creates_campaign_no_send(client, auth_headers, db_session):
    tpl = await _approved_tpl(client, auth_headers)
    resp = await client.post(
        "/api/v1/marketing/broadcast",
        json={
            "template_id": tpl["id"],
            "type": "promotional",
            "scheduled_at": _future(60),
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "scheduled"
    assert "campaign_id" in body
    assert body.get("queued", 0) == 0

    camp = await db_session.get(Campaign, body["campaign_id"])
    assert camp is not None
    assert camp.status == "scheduled"
    sends = (
        await db_session.scalars(select(MarketingSend).where(MarketingSend.campaign_id == camp.id))
    ).all()
    assert sends == []


async def test_broadcast_immediate_unchanged(client, auth_headers):
    tpl = await _approved_tpl(client, auth_headers, "sched_immediate")
    resp = await client.post(
        "/api/v1/marketing/broadcast",
        json={"template_id": tpl["id"], "type": "promotional"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert "queued" in body
    assert body.get("status") != "scheduled"


async def test_broadcast_schedule_rejects_too_soon(client, auth_headers):
    tpl = await _approved_tpl(client, auth_headers, "sched_soon")
    soon = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat().replace("+00:00", "Z")
    resp = await client.post(
        "/api/v1/marketing/broadcast",
        json={"template_id": tpl["id"], "scheduled_at": soon},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "5 minutes" in resp.json()["detail"]


async def test_cancel_scheduled_campaign(client, auth_headers, db_session):
    tpl = await _approved_tpl(client, auth_headers, "sched_cancel")
    created = await client.post(
        "/api/v1/marketing/broadcast",
        json={"template_id": tpl["id"], "scheduled_at": _future(90)},
        headers=auth_headers,
    )
    camp_id = created.json()["campaign_id"]
    resp = await client.delete(
        f"/api/v1/marketing/campaigns/{camp_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 204
    camp = await db_session.get(Campaign, camp_id)
    assert camp.status == "cancelled"


async def test_cancel_sent_campaign_409(client, auth_headers):
    tpl = await _approved_tpl(client, auth_headers, "sched_sent409")
    sent = await client.post(
        "/api/v1/marketing/broadcast",
        json={"template_id": tpl["id"]},
        headers=auth_headers,
    )
    camp_id = sent.json()["campaign_id"]
    resp = await client.delete(
        f"/api/v1/marketing/campaigns/{camp_id}",
        headers=auth_headers,
    )
    assert resp.status_code == 409


async def test_reschedule_campaign(client, auth_headers, db_session):
    tpl = await _approved_tpl(client, auth_headers, "sched_move")
    created = await client.post(
        "/api/v1/marketing/broadcast",
        json={"template_id": tpl["id"], "scheduled_at": _future(120)},
        headers=auth_headers,
    )
    camp_id = created.json()["campaign_id"]
    new_time = _future(240)
    resp = await client.patch(
        f"/api/v1/marketing/campaigns/{camp_id}/schedule",
        json={"scheduled_at": new_time},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    camp = await db_session.get(Campaign, camp_id)
    assert camp.scheduled_at is not None


async def test_scheduled_tick_sends_when_due(db_session, restaurant):
    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name="tick_due_tpl",
        language="en",
        category="marketing",
        body="Hi {{1}}, weekend deal on biryani! Reply to order now.",
        footer="Reply STOP to unsubscribe",
        buttons=[],
        status="approved",
        meta_template_id="fake-meta",
    )
    db_session.add(tpl)
    await db_session.flush()

    past = datetime.now(timezone.utc) - timedelta(minutes=10)
    camp = Campaign(
        restaurant_id=restaurant.id,
        type="promotional",
        template_id=tpl.id,
        scheduled_at=past,
        status="scheduled",
        stats={"rfm_segment": "all"},
    )
    db_session.add(camp)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500009991", name="Sched")
    db_session.add(cust)
    await db_session.commit()

    with patch("app.db.async_session_factory", _make_session_factory(db_session)):
        await _dispatch_scheduled()

    await db_session.refresh(camp)
    assert camp.status == "sent"
    sends = (
        await db_session.scalars(select(MarketingSend).where(MarketingSend.campaign_id == camp.id))
    ).all()
    assert len(sends) >= 1