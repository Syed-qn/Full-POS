from decimal import Decimal

from app.wallet.models import WalletAccount, WalletEntry


def test_wallet_tablenames():
    assert WalletAccount.__tablename__ == "wallet_accounts"
    assert WalletEntry.__tablename__ == "wallet_entries"


async def test_create_account_and_entry(db_session, seed_restaurant_customer):
    rid, cid = seed_restaurant_customer
    acc = WalletAccount(restaurant_id=rid, customer_id=cid, status="active")
    db_session.add(acc)
    await db_session.flush()
    e = WalletEntry(
        account_id=acc.id,
        restaurant_id=rid,
        amount_aed=Decimal("20.00"),
        type="refund_credit",
        status="posted",
        idempotency_key="t-1",
        created_by="system",
    )
    db_session.add(e)
    await db_session.flush()
    assert e.id is not None
