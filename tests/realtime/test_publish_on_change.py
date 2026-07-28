"""Events must follow the COMMIT, not the mutation.

The ordering FSM and the table service both flush and leave the commit to their
caller. If an event fired at mutation time, terminals would refetch while the
write was still uncommitted and often re-read the old row — a screen that looks
refreshed and is wrong, which is worse than one that is visibly late.
"""
from decimal import Decimal

import pytest

from app.realtime import bus
from app.realtime.hooks import _KEY, queue_event


@pytest.fixture(autouse=True)
def _memory_backend():
    bus.set_realtime_redis(None)
    bus._local.clear()
    yield
    bus._local.clear()


@pytest.mark.anyio
async def test_events_are_held_until_commit(db_session):
    """Queued on the session, invisible until the transaction lands."""
    queue_event(db_session, 7, "orders", order_id=1)
    assert db_session.info[_KEY] == [(7, "orders", {"order_id": 1})]


@pytest.mark.anyio
async def test_duplicate_events_collapse(db_session):
    """One request can touch several rows of the same topic. The terminal
    refetches the same list either way, so N identical events would be N
    redundant round trips on every open till."""
    for _ in range(5):
        queue_event(db_session, 7, "orders", order_id=1)
    assert len(db_session.info[_KEY]) == 1


@pytest.mark.anyio
async def test_missing_restaurant_id_is_dropped_not_guessed(db_session):
    """An event on the wrong channel would reach another branch's terminals."""
    queue_event(db_session, None, "orders", order_id=1)
    assert _KEY not in db_session.info or db_session.info[_KEY] == []


@pytest.mark.anyio
async def test_order_transition_queues_orders_kds_and_table_events(
    db_session, restaurant
):
    """The real path: moving an order queues the topics the tills listen for."""
    from app.ordering.fsm import OrderStatus, transition
    from app.ordering.models import Customer, Order

    customer = Customer(restaurant_id=restaurant.id, phone="+971500000111")
    db_session.add(customer)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number="RT-1",
        status="draft",
        priority="normal",
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("10.00"),
        total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.flush()

    await transition(db_session, order, OrderStatus.PENDING_CONFIRMATION, actor="pos")

    queued = db_session.info.get(_KEY, [])
    topics = {topic for _, topic, _ in queued}
    assert "orders" in topics
    assert "kds" in topics
    assert all(rid == restaurant.id for rid, _, _ in queued), queued
