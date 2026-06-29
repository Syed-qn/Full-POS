"""Regression: cancelling after confirm must actually cancel + release the rider.

After confirm the conv pointers (draft_order_id / pending_order_id) are cleared.
A bare cancellation message with no service call left riders delivering ghost orders.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Rider
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order
from app.whatsapp.port import InboundMessage, MessageType


def _msg(text: str, wa_id: str = "wamid.cancel1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def _conv(db_session) -> Conversation:
    return (await db_session.execute(
        select(Conversation).where(Conversation.phone == "+971501110001")
    )).scalar_one()


async def test_cancel_after_confirm_cancels_order_and_releases_rider(
    db_session, restaurant,
):
    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    rider = Rider(
        restaurant_id=restaurant.id, name="Rider", phone="+971500000099",
        status="on_delivery", performance={},
    )
    db_session.add(rider)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-0076", status=OrderStatus.CONFIRMED,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("20.00"), total=Decimal("20.00"),
        rider_id=rider.id,
    )
    db_session.add(order)
    await db_session.flush()
    batch = Batch(restaurant_id=restaurant.id, rider_id=rider.id, status="planned", route={})
    db_session.add(batch)
    await db_session.flush()
    db_session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    await db_session.flush()

    await handle_inbound(db_session, _msg("hi", "wamid.greet-cancel"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "order_placed",
        "draft_order_id": None,
        "pending_order_id": None,
    }
    await db_session.commit()

    await handle_inbound(db_session, _msg("cancel order", "wamid.cancel2"), restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(order)
    await db_session.refresh(rider)
    assert order.status == OrderStatus.CANCELLED
    assert order.rider_id is None
    assert rider.status == "available"
    bo = await db_session.scalar(select(BatchOrder).where(BatchOrder.order_id == order.id))
    assert bo is None


async def test_cancel_after_confirm_blocked_when_picked_up(db_session, restaurant):
    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    rider = Rider(
        restaurant_id=restaurant.id, name="Rider", phone="+971500000098",
        status="on_delivery", performance={},
    )
    db_session.add(rider)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id,
        order_number="R1-0077", status=OrderStatus.PICKED_UP,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("20.00"), total=Decimal("20.00"),
        rider_id=rider.id,
    )
    db_session.add(order)
    await db_session.flush()

    await handle_inbound(db_session, _msg("hi", "wamid.greet-cancel2"), restaurant_id=restaurant.id)
    await db_session.commit()
    conv = await _conv(db_session)
    conv.state = {
        **conv.state,
        "dialogue_phase": "post_order",
        "dialogue_state": "order_placed",
        "draft_order_id": None,
        "pending_order_id": None,
    }
    await db_session.commit()

    await handle_inbound(db_session, _msg("cancel order", "wamid.cancel3"), restaurant_id=restaurant.id)
    await db_session.commit()

    await db_session.refresh(order)
    assert order.status == OrderStatus.PICKED_UP