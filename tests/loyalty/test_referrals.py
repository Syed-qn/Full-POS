import re
from decimal import Decimal

import pytest

from app.loyalty import referrals as ref
from app.wallet import service as wallet


async def test_generate_referral_code_is_short_alnum_and_unique_per_owner(db_session, seed_rc):
    rid, cid = seed_rc
    code_row = await ref.generate_referral_code(db_session, restaurant_id=rid, customer_id=cid)
    assert code_row.restaurant_id == rid
    assert code_row.customer_id == cid
    assert len(code_row.code) == 6
    assert re.fullmatch(r"[A-Z0-9]{6}", code_row.code)


async def test_generate_referral_code_retries_on_collision(db_session, seed_rc, monkeypatch):
    rid, cid = seed_rc
    codes = iter(["AAAAAA", "AAAAAA", "BBBBBB"])
    monkeypatch.setattr(ref, "_random_code", lambda: next(codes))
    first = await ref.generate_referral_code(db_session, restaurant_id=rid, customer_id=cid)
    await db_session.commit()
    assert first.code == "AAAAAA"

    # Second customer, code generator collides once then succeeds.
    from app.ordering.models import Customer

    c2 = Customer(restaurant_id=rid, phone="+971500000078", name="Cust 2")
    db_session.add(c2)
    await db_session.flush()
    second = await ref.generate_referral_code(db_session, restaurant_id=rid, customer_id=c2.id)
    assert second.code == "BBBBBB"


async def test_redeem_referral_credits_both_wallets(db_session, seed_rc):
    rid, owner_id = seed_rc
    code_row = await ref.generate_referral_code(db_session, restaurant_id=rid, customer_id=owner_id)
    await db_session.commit()

    from app.ordering.models import Customer

    new_cust = Customer(restaurant_id=rid, phone="+971500000099", name="New Cust")
    db_session.add(new_cust)
    await db_session.flush()

    result = await ref.redeem_referral(
        db_session, restaurant_id=rid, code=code_row.code, new_customer_id=new_cust.id
    )
    await db_session.commit()

    assert result["referrer_customer_id"] == owner_id
    assert result["new_customer_id"] == new_cust.id
    assert new_cust.referred_by_customer_id == owner_id

    owner_acc = await wallet.get_or_create_account(db_session, restaurant_id=rid, customer_id=owner_id)
    new_acc = await wallet.get_or_create_account(db_session, restaurant_id=rid, customer_id=new_cust.id)
    assert await wallet.balance(db_session, account_id=owner_acc.id) == Decimal("10.00")
    assert await wallet.balance(db_session, account_id=new_acc.id) == Decimal("10.00")


async def test_redeem_referral_unknown_code_raises(db_session, seed_rc):
    rid, _ = seed_rc
    from app.ordering.models import Customer

    new_cust = Customer(restaurant_id=rid, phone="+971500000100", name="X")
    db_session.add(new_cust)
    await db_session.flush()
    with pytest.raises(ref.ReferralError):
        await ref.redeem_referral(
            db_session, restaurant_id=rid, code="NOPE99", new_customer_id=new_cust.id
        )


async def test_redeem_referral_rejects_already_referred_customer(db_session, seed_rc):
    rid, owner_id = seed_rc
    code_row = await ref.generate_referral_code(db_session, restaurant_id=rid, customer_id=owner_id)
    await db_session.commit()

    from app.ordering.models import Customer

    new_cust = Customer(restaurant_id=rid, phone="+971500000101", name="Y")
    db_session.add(new_cust)
    await db_session.flush()
    await ref.redeem_referral(
        db_session, restaurant_id=rid, code=code_row.code, new_customer_id=new_cust.id
    )
    await db_session.commit()

    with pytest.raises(ref.ReferralError):
        await ref.redeem_referral(
            db_session, restaurant_id=rid, code=code_row.code, new_customer_id=new_cust.id
        )


async def test_redeem_referral_is_idempotent_on_wallet_credit(db_session, seed_rc):
    """A second call after the FK is already set should not double-credit —
    guarded by the wallet idempotency key even if somehow re-invoked."""
    rid, owner_id = seed_rc
    code_row = await ref.generate_referral_code(db_session, restaurant_id=rid, customer_id=owner_id)
    await db_session.commit()

    from app.ordering.models import Customer

    new_cust = Customer(restaurant_id=rid, phone="+971500000102", name="Z")
    db_session.add(new_cust)
    await db_session.flush()
    await ref.redeem_referral(
        db_session, restaurant_id=rid, code=code_row.code, new_customer_id=new_cust.id
    )
    await db_session.commit()

    owner_acc = await wallet.get_or_create_account(db_session, restaurant_id=rid, customer_id=owner_id)
    assert await wallet.balance(db_session, account_id=owner_acc.id) == Decimal("10.00")


# --- Router-level ---


async def test_referral_code_endpoint_creates_code(db_session, client, auth_headers):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer

    r = await db_session.scalar(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    c = Customer(restaurant_id=r.id, phone="+971555001111", name="Owner")
    db_session.add(c)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(f"/api/v1/customers/{c.id}/referral-code", headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["customer_id"] == c.id
    assert len(body["code"]) == 6


async def test_referral_redeem_endpoint_credits_wallets(db_session, client, auth_headers):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer

    r = await db_session.scalar(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    owner = Customer(restaurant_id=r.id, phone="+971555002222", name="Owner2")
    new_cust = Customer(restaurant_id=r.id, phone="+971555003333", name="New2")
    db_session.add_all([owner, new_cust])
    await db_session.flush()
    await db_session.commit()

    gen = await client.post(f"/api/v1/customers/{owner.id}/referral-code", headers=auth_headers)
    code = gen.json()["code"]

    resp = await client.post(
        "/api/v1/referrals/redeem", headers=auth_headers,
        json={"code": code, "new_customer_id": new_cust.id},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["referrer_customer_id"] == owner.id
    assert body["new_customer_id"] == new_cust.id

    wallet_resp = await client.get(f"/api/v1/wallet/{new_cust.id}", headers=auth_headers)
    assert Decimal(wallet_resp.json()["balance_aed"]) == Decimal("10.00")


async def test_referral_redeem_endpoint_bad_code_400(db_session, client, auth_headers):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer

    r = await db_session.scalar(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    new_cust = Customer(restaurant_id=r.id, phone="+971555004444", name="New3")
    db_session.add(new_cust)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        "/api/v1/referrals/redeem", headers=auth_headers,
        json={"code": "ZZZZZZ", "new_customer_id": new_cust.id},
    )
    assert resp.status_code == 400
