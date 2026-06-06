from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


def _status_msg(wa_id: str = "wamid.status1") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110099",
        type=MessageType.TEXT,
        payload={"text": "where is my order"},
        restaurant_phone="+97141234567",
        timestamp=1717660900,
    )


async def _seed_active_order(db_session, status: str) -> Order:
    customer = Customer(
        restaurant_id=1, phone="+971501110099", name="StatusTest",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=1, customer_id=customer.id,
        order_number="R1-STA1", status=status,
        priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("22.00"), total=Decimal("22.00"),
        sla_confirmed_at=now,
        sla_deadline=now + timedelta(minutes=40),
    )
    db_session.add(order)
    await db_session.commit()
    return order


async def test_status_query_confirmed_order_returns_status_message(db_session):
    """'Where is my order' when order is confirmed returns a status string."""
    await _seed_active_order(db_session, OrderStatus.CONFIRMED)

    from app.menu.models import Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()

    await handle_inbound(db_session, _status_msg(), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert rows
    last = rows[-1].payload["body"].lower()
    assert any(word in last for word in ("confirmed", "preparing", "kitchen", "order", "eta"))


async def test_status_query_preparing_mentions_kitchen(db_session):
    await _seed_active_order(db_session, OrderStatus.PREPARING)

    from app.menu.models import Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()

    await handle_inbound(db_session, _status_msg(wa_id="wamid.status2"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    last = rows[-1].payload["body"].lower()
    assert "kitchen" in last or "preparing" in last


async def test_status_query_no_active_order_returns_polite_reply(db_session):
    """No active order → polite 'no recent order' message."""
    from app.menu.models import Menu
    menu = Menu(restaurant_id=1, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()

    await handle_inbound(db_session, _status_msg(wa_id="wamid.status3"), restaurant_id=1)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    assert rows
    last = rows[-1].payload["body"].lower()
    assert "order" in last
