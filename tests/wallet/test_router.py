from decimal import Decimal

from sqlalchemy import select

from app.identity.models import Restaurant
from app.ordering.models import Customer
from app.wallet import service as w


async def _restaurant_by_phone(db_session, phone: str) -> Restaurant:
    return await db_session.scalar(select(Restaurant).where(Restaurant.phone == phone))


async def test_get_wallet_returns_balance(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    c = Customer(restaurant_id=r.id, phone="+971555000111", name="C")
    db_session.add(c)
    await db_session.flush()
    await w.credit(
        db_session, restaurant_id=r.id, customer_id=c.id, amount=Decimal("25.00"),
        idempotency_key="rk-1", created_by="mgr:1",
    )
    await db_session.commit()

    resp = await client.get(f"/api/v1/wallet/{c.id}", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.json()
    assert Decimal(body["balance_aed"]) == Decimal("25.00")
    assert Decimal(body["available_aed"]) == Decimal("25.00")
    assert body["status"] == "active"


async def test_get_wallet_entries_lists_newest_first(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    c = Customer(restaurant_id=r.id, phone="+971555000222", name="C2")
    db_session.add(c)
    await db_session.flush()
    await w.credit(db_session, restaurant_id=r.id, customer_id=c.id, amount=Decimal("10.00"),
                   idempotency_key="e1", created_by="mgr:1")
    await w.credit(db_session, restaurant_id=r.id, customer_id=c.id, amount=Decimal("5.00"),
                   idempotency_key="e2", created_by="mgr:1")
    await db_session.commit()

    resp = await client.get(f"/api/v1/wallet/{c.id}/entries", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 2
    assert rows[0]["id"] > rows[1]["id"]  # newest first


async def test_cross_tenant_wallet_access_404(db_session, client, auth_headers):
    # auth_headers belongs to restaurant +971501234567. Create a DIFFERENT tenant + customer.
    other = Restaurant(name="Other", phone="+971509999999", password_hash="x", lat=25.0, lng=55.0)
    db_session.add(other)
    await db_session.flush()
    victim = Customer(restaurant_id=other.id, phone="+971555000333", name="V")
    db_session.add(victim)
    await db_session.flush()
    await db_session.commit()

    resp = await client.get(f"/api/v1/wallet/{victim.id}", headers=auth_headers)
    assert resp.status_code == 404


async def test_debit_endpoint_reduces_and_guards(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    c = Customer(restaurant_id=r.id, phone="+971555000444", name="D")
    db_session.add(c)
    await db_session.flush()
    await w.credit(db_session, restaurant_id=r.id, customer_id=c.id, amount=Decimal("20.00"),
                   idempotency_key="seed-d", created_by="mgr:1")
    await db_session.commit()

    ok = await client.post(f"/api/v1/wallet/{c.id}/debit", headers=auth_headers,
                           json={"amount_aed": "5.00", "reason": "correction"})
    assert ok.status_code == 201, ok.text
    assert ok.json()["balance_aed"] == "15.00"

    over = await client.post(f"/api/v1/wallet/{c.id}/debit", headers=auth_headers,
                             json={"amount_aed": "999.00", "reason": "too much"})
    assert over.status_code == 400
