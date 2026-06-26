"""preview_batch_groups: forecast which still-unassigned orders will batch together
(by proximity) so the order list can flag it BEFORE a rider is assigned."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.dispatch.service import preview_batch_groups
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order


async def _seed_restaurant(db_session):
    r = Restaurant(
        name="R", phone="+9710000000", password_hash="x", lat=25.2048, lng=55.2708,
        settings={},
    )
    db_session.add(r)
    await db_session.flush()
    return r


async def _order(db_session, restaurant_id, lat, lon, num, *, status="confirmed", rider_id=None):
    c = Customer(
        restaurant_id=restaurant_id, phone=f"+97150{num:07d}", name="C",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(c)
    await db_session.flush()
    addr = CustomerAddress(customer_id=c.id, latitude=lat, longitude=lon, confirmed=True)
    db_session.add(addr)
    await db_session.flush()
    now = datetime.now(timezone.utc)
    o = Order(
        restaurant_id=restaurant_id, customer_id=c.id, order_number=f"O{num}",
        status=status, priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("10.00"), total=Decimal("10.00"),
        address_id=addr.id, rider_id=rider_id, sla_confirmed_at=now,
        sla_deadline=now + timedelta(minutes=40), promised_eta=now + timedelta(minutes=40),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_nearby_unassigned_orders_share_a_preview_label(db_session):
    r = await _seed_restaurant(db_session)
    o1 = await _order(db_session, r.id, 25.2000, 55.2700, 1)
    o2 = await _order(db_session, r.id, 25.2003, 55.2702, 2)  # ~40 m from o1
    far = await _order(db_session, r.id, 25.2600, 55.3300, 3)  # several km away
    await db_session.commit()

    groups = await preview_batch_groups(db_session, restaurant_id=r.id)
    assert groups.get(o1.id) is not None
    assert groups[o1.id] == groups[o2.id]      # the two close orders share a batch
    assert far.id not in groups                # a lone order gets no preview label


async def test_assigned_orders_are_excluded_from_preview(db_session):
    r = await _seed_restaurant(db_session)
    rider = Rider(
        restaurant_id=r.id, name="Rider", phone="+971500009999", status="available",
        performance={"on_time_pct": 100.0, "avg_delivery_min": 20, "total_deliveries": 5},
    )
    db_session.add(rider)
    await db_session.flush()
    # Both nearby, but one is already assigned to a rider → not a preview candidate.
    o1 = await _order(db_session, r.id, 25.2000, 55.2700, 4)
    await _order(db_session, r.id, 25.2003, 55.2702, 5, status="assigned", rider_id=rider.id)
    await db_session.commit()

    groups = await preview_batch_groups(db_session, restaurant_id=r.id)
    # o1 has no other UNASSIGNED neighbour → no batch forecast.
    assert o1.id not in groups
