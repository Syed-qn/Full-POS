"""Native rider app: pairing → device token → background GPS ingest.

The first GPS fix must reveal the rider's stop and notify the customer (the same
gate the web tracker used), all driven by the rider-scoped /rider-app endpoints.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.dispatch.models import Batch, BatchOrder, OrderTrackingSession
from app.dispatch.rider_app import create_pairing_code
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order
from app.outbox.models import OutboxMessage


async def _seed(db_session):
    r = Restaurant(name="R", phone="+9710000000", password_hash="x", lat=25.2, lng=55.27)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="Ali", phone="+971500000010",
                  status="on_delivery", performance={})
    db_session.add(rider)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971501112233", name="Cust",
                 usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0"))
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=25.21, longitude=55.275,
                           confirmed=True, receiver_name="Cust", building="Tower 5",
                           room_apartment="123")
    db_session.add(addr)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="O1", status="picked_up",
              priority="normal", rider_id=rider.id, address_id=addr.id,
              weather_delay_disclosed=False, delivery_fee_aed=Decimal("0"),
              subtotal=Decimal("10"), total=Decimal("10"),
              sla_deadline=datetime.now(timezone.utc) + timedelta(minutes=40))
    db_session.add(o)
    await db_session.flush()
    batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="picked_up", route={"stops": []})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=1))
    now = datetime.now(timezone.utc)
    db_session.add(OrderTrackingSession(
        order_id=o.id, rider_id=rider.id, restaurant_id=r.id,
        tracking_token="tok_app", rider_token="rtok_app",
        status="active", started_at=now, expires_at=now + timedelta(hours=2),
    ))
    await db_session.commit()
    return r, rider, c, o


async def test_pair_then_location_reveals_stop_and_notifies(client, db_session):
    r, rider, c, o = await _seed(db_session)
    code = await create_pairing_code(db_session, rider=rider)
    await db_session.commit()

    # 1) Pair: code → device token
    resp = await client.post("/api/v1/rider-app/pair", json={"code": code})
    assert resp.status_code == 200
    token = resp.json()["device_token"]
    assert token
    assert resp.json()["rider_name"] == "Ali"

    # 2) First background GPS fix → reveals stop + notifies customer
    loc = await client.post(
        "/api/v1/rider-app/location",
        headers={"Authorization": f"Bearer {token}"},
        json={"latitude": 25.2055, "longitude": 55.2750, "accuracy": 8, "heading": 90},
    )
    assert loc.status_code == 200

    msgs = (await db_session.scalars(select(OutboxMessage))).all()
    keys = {m.idempotency_key for m in msgs}
    # App-only rider flow: the rider gets NO WhatsApp stop (they see it in the app).
    assert f"stop-{o.id}" not in keys
    # The customer still gets the "on the way" + track link on the first GPS ping.
    assert f"cust-picked_up-{o.id}" in keys
    # And nothing was sent to the rider's phone over WhatsApp.
    assert all(m.to_phone != rider.phone for m in msgs)

    # the order's tracking session now has the live position
    ts = await db_session.scalar(
        select(OrderTrackingSession).where(OrderTrackingSession.order_id == o.id)
    )
    assert ts.latest_latitude == 25.2055
    assert ts.last_location_at is not None


async def test_two_pings_yield_single_first_ping(db_session):
    """Two GPS fixes (the app pings from the foreground poll AND the background
    stream) must claim 'first ping' only ONCE, so the customer's picked-up
    notification can't be sent twice."""
    from app.dispatch.rider_app import record_rider_app_location

    r, rider, c, o = await _seed(db_session)

    first = await record_rider_app_location(
        db_session, rider=rider, latitude=25.2055, longitude=55.2750
    )
    second = await record_rider_app_location(
        db_session, rider=rider, latitude=25.2056, longitude=55.2751
    )

    # Only the very first fix is reported as a first ping for the order.
    assert first == [o.id]
    assert second == []


async def test_me_endpoint_returns_active_order(client, db_session):
    r, rider, c, o = await _seed(db_session)
    code = await create_pairing_code(db_session, rider=rider)
    await db_session.commit()
    token = (await client.post("/api/v1/rider-app/pair", json={"code": code})).json()["device_token"]

    me = await client.get("/api/v1/rider-app/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    body = me.json()
    assert body["riderName"] == "Ali"
    assert body["activeOrderNumber"] == "O1"
    assert body["tracking"] is True


async def test_invalid_pairing_code_rejected(client, db_session):
    await _seed(db_session)
    resp = await client.post("/api/v1/rider-app/pair", json={"code": "ZZZZZZ"})
    assert resp.status_code == 400


async def test_expired_pairing_code_rejected(client, db_session):
    r, rider, c, o = await _seed(db_session)
    code = await create_pairing_code(db_session, rider=rider)
    rider.pairing_code_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()
    resp = await client.post("/api/v1/rider-app/pair", json={"code": code})
    assert resp.status_code == 400


async def test_location_requires_valid_token(client, db_session):
    await _seed(db_session)
    resp = await client.post(
        "/api/v1/rider-app/location",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"latitude": 25.2, "longitude": 55.27},
    )
    assert resp.status_code == 401
