"""Marketing service — campaigns, template submit, compliant send, analytics.

The orchestration layer: segments + templates + throttle + window + opt-out +
outbox + coupons. Uses the MockTemplateProvider (dry-run default, approves
compliant specs synchronously) so the whole pipeline runs with no Meta calls.
"""

from datetime import datetime, timezone

import pytest

from app.marketing import service
from app.marketing.models import Campaign, MarketingSend, WaTemplate
from app.marketing.optout import record_opt_out
from app.marketing.template_mock import MockTemplateProvider
from app.marketing.template_port import TemplateCreateResult, TemplateStatus
from app.outbox.models import OutboxMessage
from app.ordering.models import Customer, Order
from sqlalchemy import func, select

# 10:00 Dubai == 06:00 UTC — inside the 09:00-18:00 UAE window.
NOW_IN_WINDOW = datetime(2026, 6, 6, 6, 0, tzinfo=timezone.utc)
# 20:00 Dubai == 16:00 UTC — outside the window.
NOW_OUT_OF_WINDOW = datetime(2026, 6, 6, 16, 0, tzinfo=timezone.utc)

_COMPLIANT_BODY = (
    "Hello! Today's special is fresh and ready. Order now to enjoy a great meal."
)


async def _seed_template(db_session, restaurant, *, body=_COMPLIANT_BODY):
    tpl = WaTemplate(
        restaurant_id=restaurant.id,
        meta_template_name="todays_special_20260606",
        language="en",
        category="marketing",
        body=body,
        footer="Reply STOP to unsubscribe",
        buttons=[],
        status="draft",
    )
    db_session.add(tpl)
    await db_session.flush()
    return tpl


async def _customer(db_session, restaurant, phone, **kwargs):
    cust = Customer(restaurant_id=restaurant.id, phone=phone, **kwargs)
    db_session.add(cust)
    await db_session.flush()
    return cust


async def _order(db_session, restaurant, customer):
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number=f"ORD-{customer.id}",
        status="delivered",
    )
    db_session.add(order)
    await db_session.flush()
    return order


# ---------------------------------------------------------------------------
# create_segment
# ---------------------------------------------------------------------------
async def test_create_segment_validates_and_stores_preview_count(db_session, restaurant):
    await _customer(db_session, restaurant, "+971500000001", total_orders=5)
    seg = await service.create_segment(
        db_session,
        restaurant_id=restaurant.id,
        name="Loyal",
        dsl={"all": [{"field": "order_count", "op": "gte", "value": 3}]},
        plain_english="loyal customers",
    )
    assert seg.id is not None
    assert seg.restaurant_id == restaurant.id
    assert seg.last_preview_count == 1


async def test_create_segment_rejects_bad_dsl(db_session, restaurant):
    with pytest.raises(ValueError):
        await service.create_segment(
            db_session,
            restaurant_id=restaurant.id,
            name="Bad",
            dsl={"all": [{"field": "nope", "op": "eq", "value": 1}]},
        )


# ---------------------------------------------------------------------------
# create_campaign
# ---------------------------------------------------------------------------
async def test_create_campaign_draft(db_session, restaurant):
    tpl = await _seed_template(db_session, restaurant)
    camp = await service.create_campaign(
        db_session,
        restaurant_id=restaurant.id,
        type="todays_special",
        template_id=tpl.id,
    )
    assert camp.status == "draft"
    assert camp.template_id == tpl.id


async def test_create_campaign_scheduled_status(db_session, restaurant):
    tpl = await _seed_template(db_session, restaurant)
    camp = await service.create_campaign(
        db_session,
        restaurant_id=restaurant.id,
        type="todays_special",
        template_id=tpl.id,
        scheduled_at=NOW_IN_WINDOW,
    )
    assert camp.status == "scheduled"


async def test_create_campaign_rejects_foreign_template(db_session, restaurant):
    tpl = await _seed_template(db_session, restaurant)
    with pytest.raises(ValueError):
        await service.create_campaign(
            db_session,
            restaurant_id=restaurant.id + 99999,
            type="todays_special",
            template_id=tpl.id,
        )


# ---------------------------------------------------------------------------
# submit_template
# ---------------------------------------------------------------------------
async def test_submit_template_approves_compliant(db_session, restaurant):
    tpl = await _seed_template(db_session, restaurant)
    provider = MockTemplateProvider()
    out = await service.submit_template(
        db_session,
        restaurant_id=restaurant.id,
        wa_template_id=tpl.id,
        provider=provider,
    )
    assert out.status == "approved"
    assert out.meta_template_id is not None
    # a datestamped name was assigned
    assert out.meta_template_name.endswith("_20260606") or "_2026" in out.meta_template_name


async def test_submit_template_lint_failure_raises(db_session, restaurant):
    tpl = await _seed_template(
        db_session, restaurant, body="Deal here: bit.ly/xyz come now please"
    )
    provider = MockTemplateProvider()
    with pytest.raises(ValueError):
        await service.submit_template(
            db_session,
            restaurant_id=restaurant.id,
            wa_template_id=tpl.id,
            provider=provider,
        )


# ---------------------------------------------------------------------------
# run_campaign_send — the core compliant pipeline
# ---------------------------------------------------------------------------
async def _approved_campaign(db_session, restaurant, provider):
    tpl = await _seed_template(db_session, restaurant)
    await service.submit_template(
        db_session,
        restaurant_id=restaurant.id,
        wa_template_id=tpl.id,
        provider=provider,
    )
    camp = await service.create_campaign(
        db_session,
        restaurant_id=restaurant.id,
        type="todays_special",
        template_id=tpl.id,
    )
    return camp


async def test_run_campaign_send_compliance_gates(db_session, restaurant):
    provider = MockTemplateProvider()
    camp = await _approved_campaign(db_session, restaurant, provider)

    # clean — should be queued
    await _customer(db_session, restaurant, "+971500000010")
    # opted out — suppressed_optout
    optout_cust = await _customer(db_session, restaurant, "+971500000011")
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone=optout_cust.phone)
    # already at cap (2 prior sends in last 24h) — suppressed_cap
    capped = await _customer(db_session, restaurant, "+971500000012")
    for _ in range(2):
        prior = Campaign(restaurant_id=restaurant.id, type="recurring")
        db_session.add(prior)
        await db_session.flush()
        db_session.add(
            MarketingSend(
                restaurant_id=restaurant.id,
                campaign_id=prior.id,
                customer_id=capped.id,
                to_phone=capped.phone,
                status="sent",
                sent_at=NOW_IN_WINDOW,
            )
        )
    await db_session.flush()

    summary = await service.run_campaign_send(
        db_session, campaign=camp, provider=provider, now_utc=NOW_IN_WINDOW
    )
    assert summary["queued"] == 1
    assert summary["suppressed_optout"] == 1
    assert summary["suppressed_cap"] == 1

    outbox_count = (
        await db_session.execute(
            select(func.count(OutboxMessage.id)).where(
                OutboxMessage.restaurant_id == restaurant.id
            )
        )
    ).scalar_one()
    assert outbox_count == 1

    statuses = {
        r.to_phone: r.status
        for r in (
            await db_session.execute(
                select(MarketingSend).where(MarketingSend.campaign_id == camp.id)
            )
        ).scalars()
    }
    assert statuses["+971500000010"] == "sent"
    assert statuses["+971500000011"] == "suppressed_optout"
    assert statuses["+971500000012"] == "suppressed_cap"

    await db_session.refresh(camp)
    assert camp.status == "sent"


async def test_run_campaign_send_outside_window_suppresses_all(db_session, restaurant):
    provider = MockTemplateProvider()
    camp = await _approved_campaign(db_session, restaurant, provider)
    await _customer(db_session, restaurant, "+971500000020")
    await _customer(db_session, restaurant, "+971500000021")

    summary = await service.run_campaign_send(
        db_session, campaign=camp, provider=provider, now_utc=NOW_OUT_OF_WINDOW
    )
    assert summary["queued"] == 0
    assert summary["suppressed_window"] == 2

    outbox_count = (
        await db_session.execute(
            select(func.count(OutboxMessage.id)).where(
                OutboxMessage.restaurant_id == restaurant.id
            )
        )
    ).scalar_one()
    assert outbox_count == 0


async def test_run_campaign_send_requires_approved_template(db_session, restaurant):
    tpl = await _seed_template(db_session, restaurant)  # status draft, not approved
    camp = await service.create_campaign(
        db_session,
        restaurant_id=restaurant.id,
        type="todays_special",
        template_id=tpl.id,
    )
    await _customer(db_session, restaurant, "+971500000030")
    with pytest.raises(ValueError):
        await service.run_campaign_send(
            db_session, campaign=camp, provider=MockTemplateProvider(),
            now_utc=NOW_IN_WINDOW,
        )


async def test_run_campaign_send_is_idempotent(db_session, restaurant):
    provider = MockTemplateProvider()
    camp = await _approved_campaign(db_session, restaurant, provider)
    await _customer(db_session, restaurant, "+971500000040")

    s1 = await service.run_campaign_send(
        db_session, campaign=camp, provider=provider, now_utc=NOW_IN_WINDOW
    )
    assert s1["queued"] == 1
    # second run must not double-insert MarketingSend rows
    await service.run_campaign_send(
        db_session, campaign=camp, provider=provider, now_utc=NOW_IN_WINDOW
    )
    send_count = (
        await db_session.execute(
            select(func.count(MarketingSend.id)).where(
                MarketingSend.campaign_id == camp.id
            )
        )
    ).scalar_one()
    assert send_count == 1


async def test_run_campaign_send_with_coupon_injects_code(db_session, restaurant):
    provider = MockTemplateProvider()
    camp = await _approved_campaign(db_session, restaurant, provider)
    camp.coupon_value = "10"
    await db_session.flush()
    cust = await _customer(db_session, restaurant, "+971500000050")
    await _order(db_session, restaurant, cust)

    await service.run_campaign_send(
        db_session, campaign=camp, provider=provider, now_utc=NOW_IN_WINDOW
    )
    row = (
        await db_session.execute(
            select(OutboxMessage).where(OutboxMessage.restaurant_id == restaurant.id)
        )
    ).scalar_one()
    # the issued coupon code appears in the template params payload
    params = str(row.payload)
    assert "SORRY-" in params


# ---------------------------------------------------------------------------
# record_send_status / record_conversion / campaign_stats
# ---------------------------------------------------------------------------
async def test_record_send_status_maps_meta_status(db_session, restaurant):
    provider = MockTemplateProvider()
    camp = await _approved_campaign(db_session, restaurant, provider)
    await _customer(db_session, restaurant, "+971500000060")
    await service.run_campaign_send(
        db_session, campaign=camp, provider=provider, now_utc=NOW_IN_WINDOW
    )
    send = (
        await db_session.execute(
            select(MarketingSend).where(MarketingSend.campaign_id == camp.id)
        )
    ).scalar_one()
    send.wa_message_id = "wamid.TEST123"
    await db_session.flush() 


# TDD GAP#3 additions: failing tests for new service helpers (poll + EOD cleanup)
# called by worker. These drive service impl before worker/celery. Use mock provider.

    await service.record_send_status(
        db_session, wa_message_id="wamid.TEST123", status="delivered"
    )
    await db_session.refresh(send)
    assert send.status == "delivered"

    # Meta silent-cap error maps to suppressed_cap
    await service.record_send_status(
        db_session, wa_message_id="wamid.TEST123", status="failed", error_code=131049
    )
    await db_session.refresh(send)
    assert send.status == "suppressed_cap"
    assert send.error_code == 131049


async def test_record_conversion_attributes_recent_send(db_session, restaurant):
    provider = MockTemplateProvider()
    camp = await _approved_campaign(db_session, restaurant, provider)
    cust = await _customer(db_session, restaurant, "+971500000070")
    order = await _order(db_session, restaurant, cust)
    await service.run_campaign_send(
        db_session, campaign=camp, provider=provider, now_utc=NOW_IN_WINDOW
    )

    await service.record_conversion(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_id=order.id,
        window_hours=48,
        now_utc=NOW_IN_WINDOW,
    )
    send = (
        await db_session.execute(
            select(MarketingSend).where(MarketingSend.customer_id == cust.id)
        )
    ).scalar_one()
    assert send.converted_order_id == order.id


async def test_campaign_stats_breakdown(db_session, restaurant):
    provider = MockTemplateProvider()
    camp = await _approved_campaign(db_session, restaurant, provider)
    clean = await _customer(db_session, restaurant, "+971500000080")
    order = await _order(db_session, restaurant, clean)
    optout_cust = await _customer(db_session, restaurant, "+971500000081")
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone=optout_cust.phone)
    await service.run_campaign_send(
        db_session, campaign=camp, provider=provider, now_utc=NOW_IN_WINDOW
    )
    await service.record_conversion(
        db_session,
        restaurant_id=restaurant.id,
        customer_id=clean.id,
        order_id=order.id,
        now_utc=NOW_IN_WINDOW,
    )

    stats = await service.campaign_stats(
        db_session, restaurant_id=restaurant.id, campaign_id=camp.id
    )
    assert stats["sent"] == 1
    assert stats["suppressed_optout"] == 1
    assert stats["converted"] == 1
    assert stats["conversion_rate"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# TDD GAP#3 (service layer for poll + EOD cleanup jobs)
# These were added first as failing, now with service impl should pass.
# ---------------------------------------------------------------------------

async def test_service_poll_template_statuses_updates_pending_meta(db_session, restaurant):
    """Poll updates pending_meta using provider (mock here)."""
    from app.marketing.models import WaTemplate
    from app.marketing.template_mock import MockTemplateProvider

    tpl = WaTemplate(
        restaurant_id=restaurant.id, meta_template_name="svc_poll_20260606",
        language="en", category="marketing", body="svc poll body", footer="STOP",
        status="pending_meta", meta_template_id="svc-meta-1", ephemeral=True
    )
    db_session.add(tpl)
    await db_session.flush()
    await db_session.commit()

    prov = MockTemplateProvider()
    async def _g(mid):
        return TemplateCreateResult(meta_template_id=mid, status=TemplateStatus.APPROVED)
    prov.get_status = _g

    updated = await service.poll_template_statuses(db_session, provider=prov)
    assert updated >= 1
    await db_session.refresh(tpl)
    assert tpl.status == "approved"


async def test_service_cleanup_ephemeral_sets_deleted(db_session, restaurant):
    """Cleanup marks ephemeral approved as deleted + sets deleted_at."""
    from datetime import datetime, timezone
    from app.marketing.models import WaTemplate
    from app.marketing.template_mock import MockTemplateProvider

    tpl = WaTemplate(
        restaurant_id=restaurant.id, meta_template_name="svc_eod_20260606",
        language="en", category="marketing", body="eod", footer="STOP",
        status="approved", ephemeral=True, meta_template_id="svc-eod-1", deleted_at=None
    )
    db_session.add(tpl)
    await db_session.flush()
    await db_session.commit()

    prov = MockTemplateProvider()
    spec_name = "svc_eod_20260606"
    await prov.create(
        type(
            "S",
            (),
            {
                "name": spec_name,
                "to_compliance_dict": lambda s: {
                    "name": spec_name,
                    "body": "b",
                    "header": None,
                    "footer": None,
                    "buttons": [],
                },
            },
        )()
    )
    prov._id_by_name[spec_name] = "svc-eod-1"
    prov._by_id["svc-eod-1"] = TemplateCreateResult(meta_template_id="svc-eod-1", status=TemplateStatus.APPROVED)

    now = datetime(2026, 6, 6, 23, 30, tzinfo=timezone.utc)
    n = await service.cleanup_ephemeral_templates(db_session, provider=prov, now=now)
    assert n >= 1
    await db_session.refresh(tpl)
    assert tpl.deleted_at is not None and tpl.status == "deleted"
