from decimal import Decimal

import pytest

from app.wallet import service as w
from app.wallet.errors import WalletError


async def test_credit_increases_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(
        db_session,
        restaurant_id=rid,
        customer_id=cid,
        amount=Decimal("20.00"),
        idempotency_key="ref-1",
        ticket_id=None,
        reason_note="cold food",
        created_by="mgr:1",
    )
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("20.00")


async def test_credit_is_idempotent(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    a = await w.credit(
        db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("20.00"),
        idempotency_key="ref-1", created_by="mgr:1",
    )
    b = await w.credit(
        db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("20.00"),
        idempotency_key="ref-1", created_by="mgr:1",
    )
    assert a.id == b.id
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("20.00")


async def test_credit_rejects_non_positive(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    with pytest.raises(WalletError):
        await w.credit(
            db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("0.00"),
            idempotency_key="z", created_by="mgr:1",
        )


async def test_debit_reduces_balance(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("30.00"),
                   idempotency_key="c", created_by="mgr:1")
    await w.debit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("10.00"),
                  idempotency_key="d1", reason_note="correction", created_by="mgr:1")
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    assert await w.balance(db_session, account_id=acc.id) == Decimal("20.00")


async def test_debit_cannot_go_negative(db_session, seed_restaurant_customer):
    from app.wallet.errors import InsufficientFunds
    rid, cid = seed_restaurant_customer
    await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("5.00"),
                   idempotency_key="c", created_by="mgr:1")
    with pytest.raises(InsufficientFunds):
        await w.debit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("10.00"),
                      idempotency_key="d1", reason_note="x", created_by="mgr:1")
