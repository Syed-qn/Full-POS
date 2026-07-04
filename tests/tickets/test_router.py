
from sqlalchemy import select

from app.identity.models import Restaurant
from app.ordering.models import Customer
from app.tickets import service as t


async def _restaurant_by_phone(db_session, phone: str) -> Restaurant:
    return await db_session.scalar(select(Restaurant).where(Restaurant.phone == phone))


async def _seed_ticket(db_session, rid: int) -> int:
    c = Customer(restaurant_id=rid, phone="+971555111000", name="C")
    db_session.add(c)
    await db_session.flush()
    tk = await t.create_ticket(
        db_session, restaurant_id=rid, customer_id=c.id, order_id=None,
        source_message="cold food",
    )
    await db_session.commit()
    return tk.id


async def test_list_and_get_ticket(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    tid = await _seed_ticket(db_session, r.id)

    listed = await client.get("/api/v1/tickets", headers=auth_headers)
    assert listed.status_code == 200
    assert any(x["id"] == tid for x in listed.json())

    got = await client.get(f"/api/v1/tickets/{tid}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["status"] == "open"


async def test_resolve_wallet_refund_endpoint(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    tid = await _seed_ticket(db_session, r.id)

    resp = await client.post(
        f"/api/v1/tickets/{tid}/resolve",
        headers=auth_headers,
        json={"action": "wallet_refund", "amount": "15.00", "note": "cold"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolution_action"] == "wallet_refund"


async def test_wallet_refund_requires_amount(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    tid = await _seed_ticket(db_session, r.id)
    resp = await client.post(
        f"/api/v1/tickets/{tid}/resolve",
        headers=auth_headers,
        json={"action": "wallet_refund", "note": "x"},
    )
    assert resp.status_code == 400


async def test_cross_tenant_ticket_404(db_session, client, auth_headers):
    other = Restaurant(name="Other2", phone="+971508888888", password_hash="x", lat=25.0, lng=55.0)
    db_session.add(other)
    await db_session.flush()
    tid = await _seed_ticket(db_session, other.id)
    resp = await client.get(f"/api/v1/tickets/{tid}", headers=auth_headers)
    assert resp.status_code == 404


async def test_list_tickets_filter_by_phone(db_session, client, auth_headers):
    from app.ordering.models import Customer
    r = await _restaurant_by_phone(db_session, "+971501234567")
    a = Customer(restaurant_id=r.id, phone="+971555777001", name="Alpha")
    b = Customer(restaurant_id=r.id, phone="+971555888002", name="Beta")
    db_session.add_all([a, b])
    await db_session.flush()
    await t.create_ticket(db_session, restaurant_id=r.id, customer_id=a.id, order_id=None, source_message="a cold")
    await t.create_ticket(db_session, restaurant_id=r.id, customer_id=b.id, order_id=None, source_message="b wrong")
    await db_session.commit()

    resp = await client.get("/api/v1/tickets?phone=777001", headers=auth_headers)
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["customer_phone"] == "+971555777001"
    assert rows[0]["customer_name"] == "Alpha"
