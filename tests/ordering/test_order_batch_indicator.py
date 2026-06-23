"""Orders list exposes rider-trip batching so the dashboard can flag matched orders.

When two orders share a batch (one rider trip), each enriched OrderOut carries
batch_id, batch_size and the full list of order numbers on the trip.
"""
from decimal import Decimal

from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Rider
from app.ordering.models import Customer, Order
from app.ordering.router import _enrich


async def _order(db_session, restaurant_id, num, customer):
    o = Order(
        restaurant_id=restaurant_id, customer_id=customer.id, order_number=num,
        status="assigned", subtotal=Decimal("10.00"), delivery_fee_aed=Decimal("0.00"),
        total=Decimal("10.00"),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_batched_orders_report_trip_members(db_session, restaurant):
    rider = Rider(restaurant_id=restaurant.id, name="Asfer", phone="+971500000099",
                  status="on_delivery", performance={})
    db_session.add(rider)
    cust = Customer(restaurant_id=restaurant.id, phone="+971501112200", name="Sara",
                    total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(cust)
    await db_session.flush()
    o1 = await _order(db_session, restaurant.id, "R1-0021", cust)
    o2 = await _order(db_session, restaurant.id, "R1-0022", cust)
    o1.rider_id = o2.rider_id = rider.id
    batch = Batch(restaurant_id=restaurant.id, rider_id=rider.id, status="planned",
                  route={"stops": []})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=o1.id, sequence=1))
    db_session.add(BatchOrder(batch_id=batch.id, order_id=o2.id, sequence=2))
    await db_session.commit()

    out1 = await _enrich(db_session, o1)
    assert out1.batch_id == batch.id
    assert out1.batch_size == 2
    assert out1.batch_order_numbers == ["R1-0021", "R1-0022"]  # delivery sequence

    out2 = await _enrich(db_session, o2)
    assert out2.batch_size == 2
    assert out2.batch_order_numbers == ["R1-0021", "R1-0022"]


async def test_solo_order_has_no_batch_size(db_session, restaurant):
    cust = Customer(restaurant_id=restaurant.id, phone="+971501112300", name="Lone",
                    total_orders=0, total_spend=Decimal("0.00"))
    db_session.add(cust)
    await db_session.flush()
    o = await _order(db_session, restaurant.id, "R1-0040", cust)
    await db_session.commit()

    out = await _enrich(db_session, o)
    assert out.batch_id is None
    assert out.batch_size is None
    assert out.batch_order_numbers == []
