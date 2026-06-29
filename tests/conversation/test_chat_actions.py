"""In-chat manager actions: customer context + manual wallet credit + issue coupon."""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.service import get_or_create_conversation
from app.identity.models import Restaurant
from app.ordering.models import Customer, Order


async def _restaurant_by_phone(db_session, phone):
    return await db_session.scalar(select(Restaurant).where(Restaurant.phone == phone))


async def _seed_customer_conv(db_session, rid, phone="+971555900001"):
    c = Customer(restaurant_id=rid, phone=phone, name="Chat Cust")
    db_session.add(c)
    await db_session.flush()
    o = Order(restaurant_id=rid, customer_id=c.id, order_number="CH-1", status="delivered",
              subtotal=Decimal("40.00"), total=Decimal("40.00"))
    db_session.add(o)
    await db_session.flush()
    conv = await get_or_create_conversation(db_session, restaurant_id=rid, phone=phone, counterpart="customer")
    await db_session.commit()
    return c, conv


async def test_chat_context_returns_orders_and_wallet(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    c, conv = await _seed_customer_conv(db_session, r.id)

    resp = await client.get(f"/api/v1/conversations/{conv.id}/context", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["customer_id"] == c.id
    assert body["wallet_balance_aed"] == "0.00"
    assert len(body["recent_orders"]) == 1
    assert body["recent_orders"][0]["order_number"] == "CH-1"


async def test_manual_wallet_credit(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    c, _ = await _seed_customer_conv(db_session, r.id, phone="+971555900002")

    resp = await client.post(
        f"/api/v1/wallet/{c.id}/credit",
        headers=auth_headers,
        json={"amount_aed": "30.00", "reason": "goodwill from chat"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["balance_aed"] == "30.00"


async def test_issue_coupon_to_customer(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    c, _ = await _seed_customer_conv(db_session, r.id, phone="+971555900003")

    resp = await client.post(
        "/api/v1/coupons/issue",
        headers=auth_headers,
        json={"customer_id": c.id, "discount_aed": "10.00"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["code"]
    assert resp.json()["discount_aed"] == "10.00"


async def test_credit_rejects_bad_amount(db_session, client, auth_headers):
    r = await _restaurant_by_phone(db_session, "+971501234567")
    c, _ = await _seed_customer_conv(db_session, r.id, phone="+971555900004")
    resp = await client.post(
        f"/api/v1/wallet/{c.id}/credit",
        headers=auth_headers,
        json={"amount_aed": "0", "reason": "x"},
    )
    assert resp.status_code == 422
