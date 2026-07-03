"""Preset marketing automations (Phase 4)."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.marketing import service
from app.marketing.models import (
    Campaign,
    MarketingAutomation,
    MarketingAutomationSend,
    RecurringMessageState,
    WaTemplate,
)
from app.ordering.models import Customer, Order
from app.ordering.service import recompute_customer_stats


async def _approved_tpl(db_session, restaurant, name="auto_tpl"):
    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name=name,
        language="en",
        category="marketing",
        body="Hi {{1}}, welcome back — order today!",
        footer="Reply STOP to opt out",
        buttons=[],
        status="approved",
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def test_ensure_automation_presets_seeds_four_rows(db_session, restaurant):
    rows = await service.ensure_automation_presets(
        db_session, restaurant_id=restaurant.id
    )
    await db_session.commit()
    assert len(rows) == 4
    keys = {r.preset_key for r in rows}
    assert keys == {"welcome", "winback", "reorder", "recurring"}


async def test_patch_automation_requires_approved_template_when_enabled(
    client, auth_headers
):
    tpl = (
        await client.post(
            "/api/v1/marketing/templates",
            json={
                "meta_template_name": "welcome_auto_tpl",
                "body": "Hi {{1}}, welcome to our kitchen — order today!",
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
    bad = await client.patch(
        "/api/v1/marketing/automations/welcome",
        json={"enabled": True},
        headers=auth_headers,
    )
    assert bad.status_code == 422
    ok = await client.patch(
        "/api/v1/marketing/automations/welcome",
        json={"enabled": True, "template_id": tpl["id"]},
        headers=auth_headers,
    )
    assert ok.status_code == 200
    assert ok.json()["enabled"] is True


async def test_on_order_delivered_schedules_welcome_for_first_order(
    db_session, restaurant
):
    tpl = await _approved_tpl(db_session, restaurant)
    auto = MarketingAutomation(
        restaurant_id=restaurant.id,
        preset_key="welcome",
        enabled=True,
        template_id=tpl.id,
        config={"delay_hours": 1},
    )
    db_session.add(auto)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000901", name="New")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="R-WEL-1",
        status="delivered",
        delivered_at=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add(order)
    await db_session.flush()
    await recompute_customer_stats(db_session, cust.id)
    await service.on_order_delivered(db_session, order=order)
    await db_session.commit()

    camp = (
        await db_session.scalars(
            select(Campaign).where(
                Campaign.restaurant_id == restaurant.id,
                Campaign.type == "automation",
            )
        )
    ).one()
    assert camp.status == "scheduled"
    assert camp.stats.get("audience_ids") == [cust.id]
    assert camp.stats.get("preset_key") == "welcome"


async def test_on_order_delivered_skips_welcome_when_not_first_order(
    db_session, restaurant
):
    tpl = await _approved_tpl(db_session, restaurant, name="welcome_skip")
    auto = MarketingAutomation(
        restaurant_id=restaurant.id,
        preset_key="welcome",
        enabled=True,
        template_id=tpl.id,
        config={"delay_hours": 1},
    )
    db_session.add(auto)
    cust = Customer(
        restaurant_id=restaurant.id,
        phone="+971500000902",
        name="Repeat",
        total_orders=2,
    )
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="R-WEL-2",
        status="delivered",
        delivered_at=datetime(2026, 6, 20, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add(order)
    await service.on_order_delivered(db_session, order=order)
    await db_session.commit()
    camps = (
        await db_session.scalars(
            select(Campaign).where(Campaign.type == "automation")
        )
    ).all()
    assert camps == []


async def test_on_order_delivered_upserts_recurring_state_day3(db_session, restaurant):
    tpl = await _approved_tpl(db_session, restaurant, name="recurring_tpl")
    auto = MarketingAutomation(
        restaurant_id=restaurant.id,
        preset_key="recurring",
        enabled=True,
        template_id=tpl.id,
        config={"lead_minutes": 15},
    )
    db_session.add(auto)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000903", name="Rec")
    db_session.add(cust)
    await db_session.flush()
    delivered = datetime(2026, 6, 20, 8, 0, tzinfo=timezone.utc)
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="R-REC-1",
        status="delivered",
        delivered_at=delivered,
        created_at=datetime(2026, 6, 20, 8, 0),
    )
    db_session.add(order)
    await db_session.flush()
    await recompute_customer_stats(db_session, cust.id)
    await service.on_order_delivered(db_session, order=order)
    await db_session.commit()

    state = (
        await db_session.scalars(select(RecurringMessageState))
    ).one()
    assert state.phase == "day3"
    assert state.customer_id == cust.id
    assert state.next_send_at > delivered


async def test_recurring_promo_tick_sends_and_advances_to_weekly(
    db_session, restaurant, monkeypatch
):
    from app.marketing.template_factory import get_template_provider

    tpl = await _approved_tpl(db_session, restaurant, name="recurring_send")
    auto = MarketingAutomation(
        restaurant_id=restaurant.id,
        preset_key="recurring",
        enabled=True,
        template_id=tpl.id,
        config={"lead_minutes": 15},
    )
    db_session.add(auto)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000904", name="Due")
    db_session.add(cust)
    await db_session.flush()
    now = datetime(2026, 6, 23, 7, 30, tzinfo=timezone.utc)
    state = RecurringMessageState(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        phase="day3",
        weekday=0,
        usual_send_local_time="12:00",
        next_send_at=now - timedelta(minutes=1),
    )
    db_session.add(state)
    await db_session.commit()

    provider = get_template_provider()
    totals = await service.run_recurring_promo_tick(
        db_session, now_utc=now, provider=provider
    )
    await db_session.commit()
    assert totals["queued"] == 1
    refreshed = await db_session.get(RecurringMessageState, state.id)
    assert refreshed is not None
    assert refreshed.phase == "weekly"
    assert (
        await db_session.scalars(select(MarketingAutomationSend))
    ).one().customer_id == cust.id


async def test_list_automations_api(client, auth_headers):
    resp = await client.get("/api/v1/marketing/automations", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 4
    assert {d["preset_key"] for d in data} == {
        "welcome",
        "winback",
        "reorder",
        "recurring",
    }