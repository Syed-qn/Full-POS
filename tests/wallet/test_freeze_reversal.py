from decimal import Decimal

import pytest

from app.wallet import service as w
from app.wallet.errors import AccountFrozen, WalletError


async def test_frozen_account_blocks_hold(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(
        db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("50.00"),
        idempotency_key="s", created_by="system",
    )
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    await w.freeze(db_session, account_id=acc.id, restaurant_id=rid, reason="abuse", created_by="mgr:1")
    with pytest.raises(AccountFrozen):
        await w.hold(
            db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("10.00"),
            order_id=1, idempotency_key="h1", created_by="system",
        )


async def test_unfreeze_restores_spend(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(
        db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("50.00"),
        idempotency_key="s", created_by="system",
    )
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    await w.freeze(db_session, account_id=acc.id, restaurant_id=rid, reason="x", created_by="mgr:1")
    await w.unfreeze(db_session, account_id=acc.id, restaurant_id=rid, created_by="mgr:1")
    e = await w.hold(
        db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("10.00"),
        order_id=1, idempotency_key="h1", created_by="system",
    )
    assert e.id is not None


async def test_reverse_credit_zeroes_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    e = await w.credit(
        db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("20.00"),
        idempotency_key="c1", created_by="mgr:1",
    )
    await w.reverse(
        db_session, entry_id=e.id, restaurant_id=rid, idempotency_key="rev-c1",
        reason_note="issued in error", created_by="mgr:1",
    )
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("0.00")


async def test_reverse_is_idempotent(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    e = await w.credit(
        db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("20.00"),
        idempotency_key="c1", created_by="mgr:1",
    )
    a = await w.reverse(
        db_session, entry_id=e.id, restaurant_id=rid, idempotency_key="rev-c1",
        reason_note="err", created_by="mgr:1",
    )
    b = await w.reverse(
        db_session, entry_id=e.id, restaurant_id=rid, idempotency_key="rev-c1",
        reason_note="err", created_by="mgr:1",
    )
    assert a.id == b.id
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("0.00")


async def test_cannot_reverse_held_entry(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(
        db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("50.00"),
        idempotency_key="s", created_by="system",
    )
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    held = await w.hold(
        db_session, account_id=acc.id, restaurant_id=rid, amount=Decimal("10.00"),
        order_id=1, idempotency_key="h1", created_by="system",
    )
    with pytest.raises(WalletError):
        await w.reverse(
            db_session, entry_id=held.id, restaurant_id=rid, idempotency_key="rev-h",
            reason_note="x", created_by="mgr:1",
        )
