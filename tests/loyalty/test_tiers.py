from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select

from app.coupons.models import Coupon
from app.loyalty import service as loy
from app.ordering.models import Customer

NOW = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)


def _cfg(loyalty_settings):
    return loyalty_settings


def test_compute_tier_reads_thresholds_from_settings(loyalty_settings):
    cfg = loyalty_settings["loyalty"]
    recent = NOW - timedelta(days=2)
    # gold defaults: 5 orders / 300 spend / 30d recency
    assert loy.compute_tier(cfg, total_orders=6, total_spend=Decimal("400"),
                            last_order_at=recent, now=NOW) == "gold"
    assert loy.compute_tier(cfg, total_orders=3, total_spend=Decimal("150"),
                            last_order_at=recent, now=NOW) == "silver"
    assert loy.compute_tier(cfg, total_orders=1, total_spend=Decimal("10"),
                            last_order_at=recent, now=NOW) is None


def test_monetary_axis_blocks_frequent_low_spender(loyalty_settings):
    cfg = loyalty_settings["loyalty"]
    recent = NOW - timedelta(days=2)
    # 6 orders but only AED 50 spend -> NOT gold (min_spend 300); falls to lower/none
    assert loy.compute_tier(cfg, total_orders=6, total_spend=Decimal("50"),
                            last_order_at=recent, now=NOW) != "gold"


def test_custom_settings_change_outcome(loyalty_settings):
    cfg = loyalty_settings["loyalty"]
    cfg["tiers"]["gold"]["min_orders"] = 2
    cfg["tiers"]["gold"]["min_spend_aed"] = 0
    recent = NOW - timedelta(days=2)
    # With the restaurant's edited thresholds, 2 orders is now Gold.
    assert loy.compute_tier(cfg, total_orders=2, total_spend=Decimal("10"),
                            last_order_at=recent, now=NOW) == "gold"


async def test_recompute_upgrades_and_issues_welcome_reward(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    c = await db_session.get(Customer, cid)
    c.total_orders = 6
    c.total_spend = Decimal("400")
    c.last_order_at = NOW - timedelta(days=1)
    await db_session.flush()
    changed, old, new = await loy.recompute_tier(db_session, customer=c, settings=loyalty_settings, now=NOW, notify=False)
    assert (changed, old, new) == (True, None, "gold")
    assert c.loyalty_tier == "gold"
    assert c.loyalty_reward_anchor == 6
    # welcome reward coupon issued
    coupons = (await db_session.scalars(select(Coupon).where(Coupon.customer_id == cid))).all()
    assert len(coupons) == 1
    assert coupons[0].discount_aed == Decimal("25.00")


async def test_disabled_program_no_tier(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    loyalty_settings["loyalty"]["enabled"] = False
    c = await db_session.get(Customer, cid)
    c.total_orders = 9
    c.total_spend = Decimal("999")
    c.last_order_at = NOW
    changed, _, _ = await loy.recompute_tier(db_session, customer=c, settings=loyalty_settings, now=NOW, notify=False)
    assert changed is False
    assert c.loyalty_tier is None


async def test_demotion_grace_holds_tier(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    c = await db_session.get(Customer, cid)
    c.loyalty_tier = "gold"
    c.total_orders = 6
    c.total_spend = Decimal("400")
    # 45 days quiet: past gold's 30d recency but within 30d grace (=60d total)
    c.last_order_at = NOW - timedelta(days=45)
    changed, _, _ = await loy.recompute_tier(db_session, customer=c, settings=loyalty_settings, now=NOW, notify=False)
    assert changed is False  # held by grace
    assert c.loyalty_tier == "gold"


async def test_demotion_after_grace(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    c = await db_session.get(Customer, cid)
    c.loyalty_tier = "gold"
    c.total_orders = 6
    c.total_spend = Decimal("400")
    c.last_order_at = NOW - timedelta(days=200)  # way past grace
    changed, old, new = await loy.recompute_tier(db_session, customer=c, settings=loyalty_settings, now=NOW, notify=False)
    assert changed is True and old == "gold"


async def test_locked_tier_skips_recompute(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    c = await db_session.get(Customer, cid)
    await loy.set_manual_tier(db_session, customer=c, tier="gold", created_by="mgr:1")
    c.total_orders = 0
    c.total_spend = Decimal("0")
    c.last_order_at = None
    changed, _, _ = await loy.recompute_tier(db_session, customer=c, settings=loyalty_settings, now=NOW, notify=False)
    assert changed is False
    assert c.loyalty_tier == "gold"  # manual override sticks


async def test_recurring_reward_every_n(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    c = await db_session.get(Customer, cid)
    c.loyalty_tier = "gold"
    c.loyalty_reward_anchor = 6  # entered gold at 6 orders; gold every_n=5
    c.total_orders = 11  # 5 orders held -> milestone
    issued = await loy.maybe_issue_recurring_reward(db_session, customer=c, settings=loyalty_settings, notify=False)
    assert issued is True
    c.total_orders = 12  # not a multiple of 5
    issued2 = await loy.maybe_issue_recurring_reward(db_session, customer=c, settings=loyalty_settings, notify=False)
    assert issued2 is False


def test_tier_progress_text(loyalty_settings):
    txt = loy.tier_progress_text(loyalty_settings, total_orders=1, total_spend=Decimal("0"),
                                 last_order_at=NOW, now=NOW)
    assert "Bronze" in txt or "Silver" in txt or "Gold" in txt
