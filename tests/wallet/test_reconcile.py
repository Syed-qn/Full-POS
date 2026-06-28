from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import update

from app.wallet import service as w
from app.wallet.models import WalletEntry
from app.wallet.reconcile import expire_credits, reconcile_tenant


async def test_reconcile_clean_ledger_zero_drift(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("30.00"),
                   idempotency_key="c1", created_by="mgr:1")
    result = await reconcile_tenant(db_session, restaurant_id=rid)
    assert result["liability_aed"] == Decimal("30.00")
    assert result["drift_aed"] == Decimal("0.00")


async def test_expiry_disabled_keeps_credit(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("30.00"),
                   idempotency_key="c1", created_by="mgr:1")
    n = await expire_credits(db_session, restaurant_id=rid, ttl_days=0)
    assert n == 0


async def test_expiry_zeroes_old_credit(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("30.00"),
                   idempotency_key="c1", created_by="mgr:1")
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    # Backdate the credit 100 days.
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=100)
    await db_session.execute(
        update(WalletEntry).where(WalletEntry.account_id == acc.id).values(created_at=old)
    )
    await db_session.flush()
    n = await expire_credits(db_session, restaurant_id=rid, ttl_days=90)
    assert n == 1
    assert await w.balance(db_session, account_id=acc.id) == Decimal("0.00")


async def test_expiry_is_idempotent(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    await w.credit(db_session, restaurant_id=rid, customer_id=cid, amount=Decimal("30.00"),
                   idempotency_key="c1", created_by="mgr:1")
    acc = await w.get_or_create_account(db_session, restaurant_id=rid, customer_id=cid)
    old = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=100)
    await db_session.execute(
        update(WalletEntry).where(WalletEntry.account_id == acc.id).values(created_at=old)
    )
    await db_session.flush()
    await expire_credits(db_session, restaurant_id=rid, ttl_days=90)
    n2 = await expire_credits(db_session, restaurant_id=rid, ttl_days=90)
    assert n2 == 0  # already expired today
    assert await w.balance(db_session, account_id=acc.id) == Decimal("0.00")
