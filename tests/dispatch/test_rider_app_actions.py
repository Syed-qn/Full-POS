"""Native rider app — Phase A: push-token registration, push on assignment, and
the in-app pickup / delivered (COD) action endpoints. These call the SAME
transport-agnostic transitions (rider_actions) as the WhatsApp flow."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.cod.models import CodCollection
from app.dispatch.models import Batch, BatchOrder, OrderTrackingSession, RiderLocation
from app.dispatch.rider_app import create_pairing_code, notify_rider_assigned
from app.identity.models import Restaurant, Rider
from app.notifications.factory import get_fake_push_provider
from app.ordering.models import Customer, CustomerAddress, Order


async def _seed(db_session, *, n_orders=1, batch_status="planned", order_status="assigned"):
    r = Restaurant(name="R", phone="+9710000001", password_hash="x", lat=25.2, lng=55.27)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="Ali", phone="+971500000011",
                  status="on_delivery", performance={})
    db_session.add(rider)
    await db_session.flush()
    batch = Batch(restaurant_id=r.id, rider_id=rider.id, status=batch_status, route={"stops": []})
    db_session.add(batch)
    await db_session.flush()
    orders = []
    now = datetime.now(timezone.utc)
    for i in range(n_orders):
        c = Customer(restaurant_id=r.id, phone=f"+97150111220{i}", name=f"Cust{i}",
                     usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0"))
        db_session.add(c)
        await db_session.flush()
        addr = CustomerAddress(customer_id=c.id, latitude=25.21, longitude=55.275,
                               confirmed=True, receiver_name=f"Cust{i}", building="Tower 5",
                               room_apartment=f"{i}01")
        db_session.add(addr)
        await db_session.flush()
        o = Order(restaurant_id=r.id, customer_id=c.id, order_number=f"O{i}", status=order_status,
                  priority="normal", rider_id=rider.id, address_id=addr.id,
                  weather_delay_disclosed=False, delivery_fee_aed=Decimal("0"),
                  subtotal=Decimal("10"), total=Decimal("10.00"),
                  sla_deadline=now + timedelta(minutes=40))
        db_session.add(o)
        await db_session.flush()
        db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=i + 1))
        db_session.add(OrderTrackingSession(
            order_id=o.id, rider_id=rider.id, restaurant_id=r.id,
            tracking_token=f"tok{i}", rider_token=f"rtok{i}",
            status="active", started_at=now, expires_at=now + timedelta(hours=2),
        ))
        orders.append(o)
    await db_session.commit()
    return r, rider, batch, orders


async def _pair(client, db_session, rider):
    code = await create_pairing_code(db_session, rider=rider)
    await db_session.commit()
    return (await client.post("/api/v1/rider-app/pair", json={"code": code})).json()["device_token"]


async def _ping(db_session, r, rider):
    db_session.add(RiderLocation(rider_id=rider.id, restaurant_id=r.id,
                                 latitude=25.2, longitude=55.27, ts=datetime.now(timezone.utc)))
    await db_session.commit()


async def test_push_token_register_then_assignment_push(client, db_session):
    r, rider, batch, orders = await _seed(db_session)
    token = await _pair(client, db_session, rider)
    fake = get_fake_push_provider()
    fake.sent.clear()

    resp = await client.post("/api/v1/rider-app/push-token",
                             headers={"Authorization": f"Bearer {token}"},
                             json={"push_token": "ExponentPushToken[abc123]"})
    assert resp.status_code == 200
    await db_session.refresh(rider)
    assert rider.push_token == "ExponentPushToken[abc123]"

    sent = await notify_rider_assigned(db_session, rider=rider, order_count=2)
    assert sent is True
    assert len(fake.sent) == 1
    assert fake.sent[0].to_token == "ExponentPushToken[abc123]"
    assert fake.sent[0].data == {"type": "assignment"}


async def test_no_push_when_rider_has_no_token(db_session):
    r, rider, batch, orders = await _seed(db_session)
    fake = get_fake_push_provider()
    fake.sent.clear()
    sent = await notify_rider_assigned(db_session, rider=rider, order_count=1)
    assert sent is False
    assert fake.sent == []


async def test_app_orders_pickup_advances_batch(client, db_session):
    r, rider, batch, orders = await _seed(db_session, n_orders=2, batch_status="planned")
    token = await _pair(client, db_session, rider)

    run = (await client.get("/api/v1/rider-app/orders",
                            headers={"Authorization": f"Bearer {token}"})).json()
    assert run["status"] == "planned"
    assert len(run["stops"]) == 2
    assert run["stops"][0]["codAmount"] == 10.0

    resp = await client.post("/api/v1/rider-app/orders/pickup",
                             headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "picked_up"

    await db_session.refresh(batch)
    assert batch.status == "picked_up"
    for o in orders:
        await db_session.refresh(o)
        assert o.status == "picked_up"


async def test_app_delivered_records_cod_and_reports_next(client, db_session):
    r, rider, batch, orders = await _seed(
        db_session, n_orders=2, batch_status="picked_up", order_status="picked_up")
    token = await _pair(client, db_session, rider)
    await _ping(db_session, r, rider)  # live GPS required to deliver

    resp = await client.post(f"/api/v1/rider-app/orders/{orders[0].id}/delivered",
                             headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["batchComplete"] is False
    assert body["nextOrderId"] == orders[1].id

    await db_session.refresh(orders[0])
    assert orders[0].status == "delivered"
    cod = await db_session.scalar(
        select(CodCollection).where(CodCollection.order_id == orders[0].id))
    assert cod is not None and cod.amount_aed == Decimal("10.00")

    # Deliver the last stop → batch complete.
    last = await client.post(f"/api/v1/rider-app/orders/{orders[1].id}/delivered",
                             headers={"Authorization": f"Bearer {token}"})
    assert last.status_code == 200
    assert last.json()["batchComplete"] is True


async def test_app_delivered_blocked_without_live_gps(client, db_session):
    r, rider, batch, orders = await _seed(
        db_session, n_orders=1, batch_status="picked_up", order_status="picked_up")
    token = await _pair(client, db_session, rider)
    # No recent ping → not live → must be rejected, order NOT advanced.
    resp = await client.post(f"/api/v1/rider-app/orders/{orders[0].id}/delivered",
                             headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 409
    await db_session.refresh(orders[0])
    assert orders[0].status == "picked_up"


async def test_app_endpoints_require_device_token(client, db_session):
    await _seed(db_session)
    assert (await client.get("/api/v1/rider-app/orders")).status_code == 401
    assert (await client.post("/api/v1/rider-app/orders/pickup")).status_code == 401
