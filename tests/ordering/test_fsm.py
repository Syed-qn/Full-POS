import pytest

from app.ordering.fsm import IllegalTransitionError, OrderFSM, OrderStatus


def test_draft_to_pending_confirmation_allowed():
    assert OrderFSM.next_states(OrderStatus.DRAFT) == {
        OrderStatus.PENDING_CONFIRMATION,
        OrderStatus.CANCELLED,
    }


def test_pending_confirmation_to_confirmed():
    OrderFSM.validate(OrderStatus.PENDING_CONFIRMATION, OrderStatus.CONFIRMED)  # should not raise


def test_illegal_transition_raises():
    with pytest.raises(IllegalTransitionError):
        OrderFSM.validate(OrderStatus.DRAFT, OrderStatus.DELIVERED)


def test_illegal_transition_from_delivered():
    with pytest.raises(IllegalTransitionError):
        OrderFSM.validate(OrderStatus.DELIVERED, OrderStatus.CONFIRMED)


def test_on_resale_to_resold_allowed():
    OrderFSM.validate(OrderStatus.ON_RESALE, OrderStatus.RESOLD)


def test_on_resale_to_written_off_allowed():
    OrderFSM.validate(OrderStatus.ON_RESALE, OrderStatus.WRITTEN_OFF)


def test_all_statuses_have_entries_in_transition_map():
    """Every OrderStatus must appear as a key in the transition map."""
    for status in OrderStatus:
        assert status in OrderFSM.TRANSITIONS, f"{status} missing from TRANSITIONS"


async def test_transition_helper_audits_and_mutates(db_session, restaurant):
    """transition() applies new status and writes an audit log row."""
    from decimal import Decimal

    from sqlalchemy import select

    from app.audit.models import AuditLog
    from app.ordering.fsm import transition
    from app.ordering.models import Customer, Order

    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501230001", name="Test",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    order = Order(
        restaurant_id=restaurant.id,
        customer_id=customer.id,
        order_number="R1-0001",
        status=OrderStatus.DRAFT,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("0.00"),
        total=Decimal("0.00"),
    )
    db_session.add(order)
    await db_session.flush()

    await transition(db_session, order, OrderStatus.PENDING_CONFIRMATION, actor="system")
    await db_session.commit()

    assert order.status == OrderStatus.PENDING_CONFIRMATION

    log = (await db_session.execute(select(AuditLog))).scalars().all()
    assert any(r.action == "order_status_transition" for r in log)
