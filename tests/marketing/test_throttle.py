"""Per-user marketing throttle: pure decision + DB 24h send count.

Pure ``can_send_marketing`` enforces order opt-out → window → cap (Meta ~2/24h,
error 131049). ``count_sends_last_24h`` backs the cap, tenant-scoped per phone.
"""

from datetime import datetime, timedelta, timezone

from app.marketing.models import Campaign, MarketingSend
from app.marketing.throttle import can_send_marketing, count_sends_last_24h
from app.ordering.models import Customer

NOW = datetime(2026, 6, 6, 10, 0, tzinfo=timezone.utc)


def test_opted_out_is_suppressed_regardless():
    d = can_send_marketing(
        now_utc=NOW, sends_last_24h=0, opted_out=True, within_window=True
    )
    assert d.allowed is False
    assert d.reason == "suppressed_optout"


def test_outside_window_is_suppressed():
    d = can_send_marketing(
        now_utc=NOW, sends_last_24h=0, opted_out=False, within_window=False
    )
    assert d.allowed is False
    assert d.reason == "suppressed_window"


def test_at_cap_is_suppressed():
    d = can_send_marketing(
        now_utc=NOW, sends_last_24h=2, opted_out=False, within_window=True,
        per_user_cap=2,
    )
    assert d.allowed is False
    assert d.reason == "suppressed_cap"


def test_under_cap_in_window_allowed():
    d = can_send_marketing(
        now_utc=NOW, sends_last_24h=1, opted_out=False, within_window=True,
        per_user_cap=2,
    )
    assert d.allowed is True
    assert d.reason == ""


def test_opt_out_precedes_window_and_cap():
    # opt-out wins even when also outside window and at cap.
    d = can_send_marketing(
        now_utc=NOW, sends_last_24h=5, opted_out=True, within_window=False
    )
    assert d.reason == "suppressed_optout"


_seq = 0


async def _send(db_session, restaurant, camp, phone, sent_at, status="sent"):
    # Customer phone is unique per tenant, so give each its own; the cap keys on
    # ``to_phone`` (the recipient), which is what we vary in the tests.
    global _seq
    _seq += 1
    cust = Customer(restaurant_id=restaurant.id, phone=f"+9715000{_seq:05d}")
    db_session.add(cust)
    await db_session.flush()
    row = MarketingSend(
        restaurant_id=restaurant.id,
        campaign_id=camp.id,
        customer_id=cust.id,
        to_phone=phone,
        status=status,
        sent_at=sent_at,
    )
    db_session.add(row)
    await db_session.flush()
    return row


async def test_count_sends_last_24h_counts_only_trailing_window(db_session, restaurant):
    camp = Campaign(restaurant_id=restaurant.id, type="todays_special")
    db_session.add(camp)
    await db_session.flush()
    phone = "+971501112233"
    await _send(db_session, restaurant, camp, phone, NOW - timedelta(hours=1))
    await _send(db_session, restaurant, camp, phone, NOW - timedelta(hours=23))
    # Outside the trailing 24h window — excluded.
    await _send(db_session, restaurant, camp, phone, NOW - timedelta(hours=25))

    count = await count_sends_last_24h(
        db_session, restaurant_id=restaurant.id, phone=phone, now_utc=NOW
    )
    assert count == 2


async def test_count_sends_last_24h_is_tenant_and_phone_scoped(db_session, restaurant):
    camp = Campaign(restaurant_id=restaurant.id, type="todays_special")
    db_session.add(camp)
    await db_session.flush()
    await _send(db_session, restaurant, camp, "+971500000010", NOW - timedelta(hours=1))

    # Different phone for same restaurant is not counted.
    count = await count_sends_last_24h(
        db_session, restaurant_id=restaurant.id, phone="+971599999999", now_utc=NOW
    )
    assert count == 0
    # Different restaurant is not counted.
    count = await count_sends_last_24h(
        db_session, restaurant_id=restaurant.id + 99999,
        phone="+971500000010", now_utc=NOW,
    )
    assert count == 0


async def test_count_excludes_suppressed_and_failed(db_session, restaurant):
    camp = Campaign(restaurant_id=restaurant.id, type="todays_special")
    db_session.add(camp)
    await db_session.flush()
    phone = "+971502223344"
    await _send(db_session, restaurant, camp, phone, NOW - timedelta(hours=1), status="sent")
    await _send(
        db_session, restaurant, camp, phone, NOW - timedelta(hours=1),
        status="suppressed_cap",
    )
    await _send(
        db_session, restaurant, camp, phone, NOW - timedelta(hours=1), status="failed"
    )

    count = await count_sends_last_24h(
        db_session, restaurant_id=restaurant.id, phone=phone, now_utc=NOW
    )
    assert count == 1
