from decimal import Decimal

import pytest

from app.wallet import service as w
from app.wallet.errors import InsufficientFunds


async def _funded(db_session, rid, cid, amt="50.00"):
    await w.credit(
        db_session, restaurant_id=rid, customer_id=cid, amount=Decimal(amt),
        idempotency_key=f"seed-{rid}-{cid}", created_by="system",
    )
    return await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)


async def test_hold_reduces_available_not_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid)
    await w.hold(
        db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
        order_id=100, idempotency_key="hold:100", created_by="system",
    )
    assert await w.balance(db_session, account_id=acc.id) == Decimal("50.00")
    assert await w.available(db_session, account_id=acc.id) == Decimal("30.00")


async def test_hold_is_idempotent(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid)
    a = await w.hold(
        db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
        order_id=100, idempotency_key="hold:100", created_by="system",
    )
    b = await w.hold(
        db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
        order_id=100, idempotency_key="hold:100", created_by="system",
    )
    assert a.id == b.id
    assert await w.available(db_session, account_id=acc.id) == Decimal("30.00")


async def test_hold_rejects_over_available(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid, "10.00")
    with pytest.raises(InsufficientFunds):
        await w.hold(
            db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
            order_id=1, idempotency_key="hold:1", created_by="system",
        )


async def test_capture_posts_debit_and_nets_hold(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid)
    await w.hold(
        db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
        order_id=100, idempotency_key="hold:100", created_by="system",
    )
    await w.capture(
        db_session, account_id=acc.id, restaurant_id=rid, order_id=100,
        idempotency_key="cap:100", created_by="system",
    )
    assert await w.balance(db_session, account_id=acc.id) == Decimal("30.00")
    assert await w.available(db_session, account_id=acc.id) == Decimal("30.00")


async def test_release_returns_credit_to_available(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid)
    await w.hold(
        db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
        order_id=100, idempotency_key="hold:100", created_by="system",
    )
    await w.release(
        db_session, account_id=acc.id, restaurant_id=rid, order_id=100,
        idempotency_key="rel:100", created_by="system",
    )
    assert await w.balance(db_session, account_id=acc.id) == Decimal("50.00")
    assert await w.available(db_session, account_id=acc.id) == Decimal("50.00")


async def test_concurrent_two_orders_cannot_double_spend(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = await _funded(db_session, rid, cid, "20.00")
    await w.hold(
        db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
        order_id=1, idempotency_key="hold:1", created_by="system",
    )
    with pytest.raises(InsufficientFunds):
        await w.hold(
            db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("20.00"),
            order_id=2, idempotency_key="hold:2", created_by="system",
        )
