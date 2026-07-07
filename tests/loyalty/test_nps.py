from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.loyalty import nps


async def _order(db_session, rid, cid, order_number="N-1"):
    from app.ordering.models import Order

    o = Order(
        restaurant_id=rid, customer_id=cid, order_number=order_number, status="delivered",
        subtotal=Decimal("50.00"), total=Decimal("50.00"),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_record_nps_response_persists(db_session, seed_rc):
    rid, cid = seed_rc
    o = await _order(db_session, rid, cid)
    resp = await nps.record_nps_response(
        db_session, restaurant_id=rid, customer_id=cid, order_id=o.id, score=9, comment="great!"
    )
    await db_session.commit()
    assert resp.id is not None
    assert resp.score == 9
    assert resp.comment == "great!"
    assert resp.restaurant_id == rid
    assert resp.order_id == o.id


@pytest.mark.parametrize("bad_score", [-1, 11, 100])
async def test_record_nps_response_rejects_out_of_range_score(db_session, seed_rc, bad_score):
    rid, cid = seed_rc
    o = await _order(db_session, rid, cid)
    with pytest.raises(ValueError):
        await nps.record_nps_response(
            db_session, restaurant_id=rid, customer_id=cid, order_id=o.id, score=bad_score, comment=None
        )


async def test_nps_summary_computes_formula(db_session, seed_rc):
    rid, cid = seed_rc
    scores = [9, 10, 9, 7, 8, 0, 3, 6]  # promoters(9,10)=3, detractors(0-6)=3, passives(7,8)=2
    for i, score in enumerate(scores):
        o = await _order(db_session, rid, cid, order_number=f"N-{i}")
        await nps.record_nps_response(
            db_session, restaurant_id=rid, customer_id=cid, order_id=o.id, score=score, comment=None
        )
    await db_session.commit()

    today = date.today()
    summary = await nps.nps_summary(
        db_session, restaurant_id=rid,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=1),
    )
    assert summary["total_responses"] == 8
    assert summary["promoters"] == 3
    assert summary["passives"] == 2
    assert summary["detractors"] == 3
    # (3 - 3) / 8 * 100 = 0.0
    assert summary["nps_score"] == 0.0


async def test_nps_summary_all_promoters_is_100(db_session, seed_rc):
    rid, cid = seed_rc
    for i, score in enumerate([9, 10, 9]):
        o = await _order(db_session, rid, cid, order_number=f"P-{i}")
        await nps.record_nps_response(
            db_session, restaurant_id=rid, customer_id=cid, order_id=o.id, score=score, comment=None
        )
    await db_session.commit()
    today = date.today()
    summary = await nps.nps_summary(
        db_session, restaurant_id=rid,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=1),
    )
    assert summary["nps_score"] == 100.0


async def test_nps_summary_empty_range_zero_responses(db_session, seed_rc):
    rid, _ = seed_rc
    today = date.today()
    summary = await nps.nps_summary(
        db_session, restaurant_id=rid,
        start_date=today - timedelta(days=1), end_date=today + timedelta(days=1),
    )
    assert summary == {
        "nps_score": 0.0, "promoters": 0, "passives": 0, "detractors": 0, "total_responses": 0,
    }


# --- Router-level ---


async def test_nps_order_endpoint_records_response(db_session, client, auth_headers):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    r = await db_session.scalar(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    c = Customer(restaurant_id=r.id, phone="+971555005555", name="Nps Cust")
    db_session.add(c)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="NR-1", status="delivered",
              subtotal=Decimal("40.00"), total=Decimal("40.00"))
    db_session.add(o)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{o.id}/nps", headers=auth_headers,
        json={"customer_id": c.id, "score": 10, "comment": "loved it"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["score"] == 10
    assert body["order_id"] == o.id


async def test_nps_order_endpoint_rejects_bad_score(db_session, client, auth_headers):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    r = await db_session.scalar(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    c = Customer(restaurant_id=r.id, phone="+971555006666", name="Nps Cust 2")
    db_session.add(c)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="NR-2", status="delivered",
              subtotal=Decimal("40.00"), total=Decimal("40.00"))
    db_session.add(o)
    await db_session.flush()
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/orders/{o.id}/nps", headers=auth_headers,
        json={"customer_id": c.id, "score": 42, "comment": None},
    )
    assert resp.status_code == 422


async def test_nps_summary_report_endpoint(db_session, client, auth_headers):
    from sqlalchemy import select

    from app.identity.models import Restaurant
    from app.ordering.models import Customer, Order

    r = await db_session.scalar(select(Restaurant).where(Restaurant.phone == "+971501234567"))
    c = Customer(restaurant_id=r.id, phone="+971555007777", name="Nps Cust 3")
    db_session.add(c)
    await db_session.flush()
    for i, score in enumerate([10, 2]):
        o = Order(restaurant_id=r.id, customer_id=c.id, order_number=f"NR-3-{i}", status="delivered",
                  subtotal=Decimal("40.00"), total=Decimal("40.00"))
        db_session.add(o)
        await db_session.flush()
        await nps.record_nps_response(
            db_session, restaurant_id=r.id, customer_id=c.id, order_id=o.id, score=score, comment=None
        )
    await db_session.commit()

    today = date.today()
    resp = await client.get(
        "/api/v1/reports/nps-summary",
        headers=auth_headers,
        params={"start_date": str(today - timedelta(days=1)), "end_date": str(today + timedelta(days=1))},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_responses"] == 2
    assert body["promoters"] == 1
    assert body["detractors"] == 1
