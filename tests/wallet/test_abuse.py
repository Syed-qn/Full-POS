from decimal import Decimal

from app.tickets import service as tickets
from app.wallet import service as w
from app.wallet.abuse import check_and_flag, refund_velocity


async def _refund_via_ticket(db_session, rid, cid, amount, n):
    tk = await tickets.create_ticket(db_session, restaurant_id=rid, customer_id=cid,
                                     order_id=None, source_message=f"complaint {n}")
    await tickets.resolve_wallet_refund(db_session, restaurant_id=rid, ticket_id=tk.id,
                                        amount=Decimal(amount), note="goodwill", created_by="mgr:1")


async def test_velocity_counts_refunds(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await _refund_via_ticket(db_session, rid, cid, "10.00", 1)
    await _refund_via_ticket(db_session, rid, cid, "10.00", 2)
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    v = await refund_velocity(db_session, account_id=acc.id, window_days=30)
    assert v["count"] == 2
    assert v["total_aed"] == Decimal("20.00")


async def test_over_cap_freezes_account(db_session, seed_restaurant_customer, monkeypatch):
    from app import config
    config.get_settings.cache_clear()
    monkeypatch.setenv("APP_WALLET_REFUND_MAX_COUNT", "2")
    monkeypatch.setenv("APP_WALLET_REFUND_MAX_AED", "1000")
    monkeypatch.setenv("APP_WALLET_REFUND_WINDOW_DAYS", "30")
    config.get_settings.cache_clear()

    rid, cid = seed_restaurant_customer
    # 3 refunds > cap of 2 -> frozen.
    await _refund_via_ticket(db_session, rid, cid, "10.00", 1)
    await _refund_via_ticket(db_session, rid, cid, "10.00", 2)
    await _refund_via_ticket(db_session, rid, cid, "10.00", 3)
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert acc.status == "frozen"
    config.get_settings.cache_clear()


async def test_under_cap_not_frozen(db_session, seed_restaurant_customer, monkeypatch):
    from app import config
    config.get_settings.cache_clear()
    monkeypatch.setenv("APP_WALLET_REFUND_MAX_COUNT", "5")
    monkeypatch.setenv("APP_WALLET_REFUND_MAX_AED", "1000")
    monkeypatch.setenv("APP_WALLET_REFUND_WINDOW_DAYS", "30")
    config.get_settings.cache_clear()

    rid, cid = seed_restaurant_customer
    await _refund_via_ticket(db_session, rid, cid, "10.00", 1)
    flagged = await check_and_flag(db_session, restaurant_id=rid, customer_id=cid)
    assert flagged is False
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert acc.status == "active"
    config.get_settings.cache_clear()
