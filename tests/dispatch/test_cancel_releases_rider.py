"""Cancelling an assigned order must detach it from the rider (no ghost deliveries)."""
from decimal import Decimal

from sqlalchemy import select

from app.dispatch.models import Batch, BatchOrder
from app.dispatch.service import release_order_from_dispatch
from app.identity.models import Restaurant, Rider
from app.ordering import service as ordering
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order


async def _seed_assigned(db_session):
    r = Restaurant(name="Disp R", phone="+97140000200", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    rider = Rider(restaurant_id=r.id, name="Rider A", phone="+971500200001", status="on_delivery")
    db_session.add(rider)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500200002", name="C")
    db_session.add(c)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="D-1",
              status=OrderStatus.ASSIGNED, subtotal=Decimal("30"), total=Decimal("30"),
              rider_id=rider.id)
    db_session.add(o)
    await db_session.flush()
    batch = Batch(restaurant_id=r.id, rider_id=rider.id, status="planned", route={})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=o.id, sequence=1))
    await db_session.flush()
    return r, rider, c, o, batch


async def test_release_detaches_and_frees_rider(db_session):
    r, rider, c, o, batch = await _seed_assigned(db_session)
    released = await release_order_from_dispatch(db_session, order=o, actor="customer")
    assert released is True
    assert o.rider_id is None
    # batch stop gone
    bo = await db_session.scalar(select(BatchOrder).where(BatchOrder.order_id == o.id))
    assert bo is None
    # rider freed (no other live orders)
    assert rider.status == "available"
    # emptied batch completed
    b = await db_session.get(Batch, batch.id)
    assert b.status == "completed"


async def test_cancel_preparing_with_rider_releases_dispatch(db_session):
    # Real scenario: order in PREPARING with a rider attached (pre-assign/race) is
    # cancelled → resale path. The rider must be detached so they aren't told to
    # collect cancelled food.
    r, rider, c, o, batch = await _seed_assigned(db_session)
    o.status = OrderStatus.PREPARING
    await db_session.flush()
    await ordering.cancel_order(db_session, order=o, actor="customer", reason="changed mind")
    assert o.status == OrderStatus.ON_RESALE
    assert o.rider_id is None
    bo = await db_session.scalar(select(BatchOrder).where(BatchOrder.order_id == o.id))
    assert bo is None
    assert rider.status == "available"


async def test_release_noop_when_never_dispatched(db_session):
    r = Restaurant(name="ND R", phone="+97140000201", password_hash="x", lat=25.2, lng=55.2)
    db_session.add(r)
    await db_session.flush()
    c = Customer(restaurant_id=r.id, phone="+971500200003", name="C")
    db_session.add(c)
    await db_session.flush()
    o = Order(restaurant_id=r.id, customer_id=c.id, order_number="ND-1",
              status=OrderStatus.CONFIRMED, subtotal=Decimal("30"), total=Decimal("30"))
    db_session.add(o)
    await db_session.flush()
    released = await release_order_from_dispatch(db_session, order=o, actor="customer")
    assert released is False
