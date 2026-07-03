"""Integration tests for the Today's Special auto-timed tick (service level).

Seeds a customer with a clustered noon ordering habit and verifies the tick
sends them the special ~15 min before, once per day, only when enabled.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select

from app.marketing import service
from app.marketing.models import Campaign, MarketingSend, WaTemplate
from app.outbox.models import OutboxMessage
from app.ordering.models import Customer, Order

# 11:50 Dubai == 07:50 UTC. A noon (12:00) habit minus 15-min lead = 11:45 send
# target, so 11:50 is "due". 10:00 Dubai (06:00 UTC) is before the target.
NOW_DUE = datetime(2026, 6, 22, 7, 50, tzinfo=timezone.utc)
NOW_NOT_DUE = datetime(2026, 6, 22, 6, 0, tzinfo=timezone.utc)


async def _approved_template(db_session, restaurant):
    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name="todays_special_20260622",
        language="en",
        category="marketing",
        body="Hi {{1}}! Today's special is fresh and ready — order now to enjoy.",
        footer="Reply STOP to unsubscribe",
        buttons=[],
        status="approved",
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _noon_customer(db_session, restaurant, phone="+971500000123"):
    cust = Customer(restaurant_id=restaurant.id, phone=phone, name="Layla")
    db_session.add(cust)
    await db_session.flush()
    # Three Monday lunch orders at 08:00 UTC == 12:00 Dubai (tick day is Monday).
    db_session.add_all([
        Order(
            restaurant_id=restaurant.id, customer_id=cust.id,
            order_number=f"R-N{i}", status="delivered",
            created_at=datetime(2026, 6, 8 + i * 7, 8, 0),
        )
        for i in range(3)
    ])
    await db_session.flush()
    return cust


def _enable(restaurant, template_id, **over):
    cfg = {"enabled": True, "template_id": template_id, "lead_minutes": 15, "default_time": "11:45"}
    cfg.update(over)
    restaurant.settings = {**(restaurant.settings or {}), "todays_special": cfg}


async def test_tick_uses_fallback_when_primary_rejected(db_session, restaurant):
    primary = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name="special_primary_rej",
        language="en",
        category="marketing",
        body="Hi {{1}}! Primary special.",
        footer="Reply STOP to unsubscribe",
        buttons=[],
        status="rejected",
    )
    fallback = await _approved_template(db_session, restaurant)
    fallback.meta_template_name = "special_fallback_ok"
    db_session.add(primary)
    await db_session.flush()
    cust = await _noon_customer(db_session, restaurant)
    _enable(restaurant, primary.id, fallback_template_id=fallback.id)
    await db_session.flush()

    totals = await service.run_todays_special_tick(db_session, now_utc=NOW_DUE)
    await db_session.commit()

    assert totals["queued"] == 1
    send = (await db_session.scalars(
        select(MarketingSend).where(MarketingSend.customer_id == cust.id)
    )).one()
    camp = await db_session.get(Campaign, send.campaign_id)
    assert camp.stats.get("template_source") == "fallback"


async def test_tick_sends_special_at_predicted_time(db_session, restaurant):
    tpl = await _approved_template(db_session, restaurant)
    cust = await _noon_customer(db_session, restaurant)
    _enable(restaurant, tpl.id)
    await db_session.flush()

    totals = await service.run_todays_special_tick(db_session, now_utc=NOW_DUE)
    await db_session.commit()

    assert totals["queued"] == 1
    assert restaurant.id in totals["restaurants"]
    send = (await db_session.scalars(
        select(MarketingSend).where(MarketingSend.customer_id == cust.id)
    )).one()
    assert send.status == "sent"
    outbox = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == cust.phone)
    )).all()
    assert len(outbox) == 1


async def test_tick_is_idempotent_within_the_day(db_session, restaurant):
    tpl = await _approved_template(db_session, restaurant)
    cust = await _noon_customer(db_session, restaurant)
    _enable(restaurant, tpl.id)
    await db_session.flush()

    first = await service.run_todays_special_tick(db_session, now_utc=NOW_DUE)
    await db_session.commit()
    # A later tick the same day must NOT re-send (per-day campaign + unique ledger).
    later = NOW_DUE.replace(minute=55)
    second = await service.run_todays_special_tick(db_session, now_utc=later)
    await db_session.commit()

    assert first["queued"] == 1
    assert second["queued"] == 0
    sends = (await db_session.scalar(
        select(func.count(MarketingSend.id)).where(MarketingSend.customer_id == cust.id)
    ))
    assert sends == 1


async def test_tick_noop_when_disabled(db_session, restaurant):
    tpl = await _approved_template(db_session, restaurant)
    await _noon_customer(db_session, restaurant)
    _enable(restaurant, tpl.id, enabled=False)
    await db_session.flush()

    totals = await service.run_todays_special_tick(db_session, now_utc=NOW_DUE)
    await db_session.commit()

    assert totals["queued"] == 0
    count = await db_session.scalar(select(func.count(MarketingSend.id)))
    assert count == 0


async def test_tick_skips_customer_not_yet_due(db_session, restaurant):
    tpl = await _approved_template(db_session, restaurant)
    await _noon_customer(db_session, restaurant)
    _enable(restaurant, tpl.id)
    await db_session.flush()

    totals = await service.run_todays_special_tick(db_session, now_utc=NOW_NOT_DUE)
    await db_session.commit()

    assert totals["queued"] == 0
    count = await db_session.scalar(select(func.count(MarketingSend.id)))
    assert count == 0


async def test_tick_uses_default_time_for_sparse_customer(db_session, restaurant):
    """A customer with too little history is sent at the restaurant default time
    (11:45 here), not skipped — so new customers still get the special."""
    tpl = await _approved_template(db_session, restaurant)
    cust = Customer(restaurant_id=restaurant.id, phone="+971500000999", name="New")
    db_session.add(cust)
    await db_session.flush()
    db_session.add(Order(
        restaurant_id=restaurant.id, customer_id=cust.id,
        order_number="R-NEW1", status="delivered",
        created_at=datetime(2026, 6, 20, 3, 0),  # one order at an odd hour
    ))
    _enable(restaurant, tpl.id)  # default_time 11:45 → due at NOW_DUE (11:50)
    await db_session.flush()

    totals = await service.run_todays_special_tick(db_session, now_utc=NOW_DUE)
    await db_session.commit()

    assert totals["queued"] == 1
    send = (await db_session.scalars(
        select(MarketingSend).where(MarketingSend.customer_id == cust.id)
    )).one()
    assert send.status == "sent"
