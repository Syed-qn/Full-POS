"""finalize_confirmation must be a no-op on an already-confirmed order.

Called twice (stale button, modify race, replayed caller) it previously skipped
the FSM transitions without erroring, then silently RESTARTED the SLA clock,
re-applied the wallet hold and re-pushed to the partner — giving the kitchen a
fresh 40 minutes the customer was never told about.
"""
from decimal import Decimal

from app.ordering.models import Customer, Order
from app.ordering.service import finalize_confirmation


async def _confirmed_order(db_session, restaurant):
    c = Customer(restaurant_id=restaurant.id, phone="+971500002211", name="Fin")
    db_session.add(c)
    await db_session.flush()
    o = Order(
        restaurant_id=restaurant.id, customer_id=c.id, order_number="FIN-1",
        status="draft", subtotal=Decimal("30.00"), total=Decimal("30.00"),
        delivery_fee_aed=Decimal("0.00"),
    )
    db_session.add(o)
    await db_session.flush()
    return o


async def test_second_finalize_does_not_restart_sla(db_session, restaurant):
    order = await _confirmed_order(db_session, restaurant)

    await finalize_confirmation(db_session, order=order, actor="customer")
    assert str(order.status) == "confirmed"
    first_deadline = order.sla_deadline
    first_confirmed_at = order.sla_confirmed_at
    assert first_deadline is not None

    # Replay — must be a pure no-op, not a silent SLA restart.
    await finalize_confirmation(db_session, order=order, actor="customer")

    assert str(order.status) == "confirmed"
    assert order.sla_deadline == first_deadline
    assert order.sla_confirmed_at == first_confirmed_at
