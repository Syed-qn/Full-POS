from decimal import Decimal

from app.loyalty import service as loy
from app.ordering.models import Order
from app.wallet import service as wallet


async def _order(db_session, rid, cid, subtotal="100.00"):
    o = Order(restaurant_id=rid, customer_id=cid, order_number="L-1", status="delivered",
              subtotal=Decimal(subtotal), total=Decimal(subtotal))
    db_session.add(o)
    await db_session.flush()
    return o


async def test_earn_credits_wallet_from_settings_rate(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    o = await _order(db_session, rid, cid, "100.00")  # 5% -> 5.00
    amt = await loy.earn(db_session, order=o, settings=loyalty_settings)
    assert amt == Decimal("5.00")
    acc = await wallet.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("5.00")


async def test_earn_respects_per_order_cap(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    loyalty_settings["loyalty"]["earn_max_per_order_aed"] = 3.0
    o = await _order(db_session, rid, cid, "200.00")  # 5% = 10 -> capped at 3
    amt = await loy.earn(db_session, order=o, settings=loyalty_settings)
    assert amt == Decimal("3.00")


async def test_earn_idempotent_per_order(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    o = await _order(db_session, rid, cid, "100.00")
    await loy.earn(db_session, order=o, settings=loyalty_settings)
    await loy.earn(db_session, order=o, settings=loyalty_settings)  # replay
    acc = await wallet.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("5.00")  # not 10


async def test_earn_disabled_no_credit(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    loyalty_settings["loyalty"]["enabled"] = False
    o = await _order(db_session, rid, cid, "100.00")
    amt = await loy.earn(db_session, order=o, settings=loyalty_settings)
    assert amt == Decimal("0.00")


async def test_reverse_earn_claws_back(db_session, seed_rc, loyalty_settings):
    rid, cid = seed_rc
    o = await _order(db_session, rid, cid, "100.00")
    await loy.earn(db_session, order=o, settings=loyalty_settings)
    await loy.reverse_earn(db_session, order=o)
    acc = await wallet.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await wallet.balance(db_session, account_id=acc.id) == Decimal("0.00")
