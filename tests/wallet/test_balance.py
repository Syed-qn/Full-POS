from decimal import Decimal

from app.wallet import service as w


async def test_new_account_zero_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("0.00")
    assert await w.available(db_session, account_id=acc.id) == Decimal("0.00")


async def test_get_or_create_is_idempotent(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    a = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    b = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert a.id == b.id
