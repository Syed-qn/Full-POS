"""Rider sees a "don't call" flag when the customer set the preference.

``Customer.tags['do_not_call']`` flows through ``_stop_details`` into both the
native rider-app run view (``get_active_run`` → ``StopView.do_not_call``) and the
WhatsApp stop message (``_stop_body`` shows a clear "don't call" line instead of a
call hint).
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.dispatch.models import Batch, BatchOrder
from app.dispatch.rider_actions import get_active_run
from app.dispatch.rider_flow import _stop_body, _stop_details
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order


async def _seed_order(db_session, *, do_not_call: bool):
    r = Restaurant(name="R", phone="+9710000777", password_hash="x", lat=25.2, lng=55.27)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="Ali", phone="+971500007770",
                  status="on_delivery", performance={})
    db_session.add(rider)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971501230000", name="Sara",
                 usual_order_times={}, tags={"do_not_call": True} if do_not_call else {},
                 total_orders=0, total_spend=Decimal("0"))
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=25.21, longitude=55.275,
                           confirmed=True, receiver_name="Sara", building="Tower 5",
                           room_apartment="101")
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="O1", status="assigned",
              priority="normal", rider_id=rider.id, address_id=addr.id,
              weather_delay_disclosed=False, delivery_fee_aed=Decimal("0"),
              subtotal=Decimal("10"), total=Decimal("10.00"),
              sla_deadline=now + timedelta(minutes=40))
    db_session.add(o)
    await db_session.flush()
    batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="planned", route={"stops": []})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=1))
    await db_session.commit()
    return r, rider, o


async def test_stop_details_and_body_carry_do_not_call(db_session):
    _, _, o = await _seed_order(db_session, do_not_call=True)
    name, address, coords, phone, dnc = await _stop_details(db_session, o)
    assert dnc is True
    body = _stop_body(o, name, address, coords, phone=phone, do_not_call=dnc)
    assert "DON'T call" in body or "don't call" in body.lower()


async def test_active_run_exposes_do_not_call(db_session):
    _, rider, _ = await _seed_order(db_session, do_not_call=True)
    run = await get_active_run(db_session, rider=rider)
    assert run is not None
    assert run.stops[0].do_not_call is True


async def test_no_flag_when_customer_did_not_ask(db_session):
    _, rider, o = await _seed_order(db_session, do_not_call=False)
    _, _, _, _, dnc = await _stop_details(db_session, o)
    assert dnc is False
    run = await get_active_run(db_session, rider=rider)
    assert run.stops[0].do_not_call is False
