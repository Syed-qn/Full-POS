"""
Integration test: inbound text → handle_inbound → outbox enqueued → MockProvider send.
Mirrors the pipeline test pattern from Phase 2.
"""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.outbox.models import OutboxMessage
from app.whatsapp.mock_provider import MockProvider
from app.whatsapp.port import InboundMessage, MessageType, OutboundMessage, OutboundMessageType


async def _seed_menu(db_session, restaurant_id):
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"),
        category="Rice", is_available=True, name_normalized="chicken biryani",
    ))
    await db_session.commit()


async def test_full_greeting_pipeline_via_mock_provider(db_session, restaurant):
    """Greeting → handle_inbound → outbox row → MockProvider.send delivers it."""
    await _seed_menu(db_session, restaurant.id)

    inbound = InboundMessage(
        wa_message_id="wamid.pipeline-1",
        from_phone="+971509000001",
        type=MessageType.TEXT,
        payload={"text": "hi"},
        restaurant_phone=restaurant.phone,
        timestamp=1717660900,
    )

    await handle_inbound(db_session, inbound, restaurant_id=restaurant.id)
    await db_session.commit()

    # Simulate outbox worker: send all pending rows via MockProvider
    provider = MockProvider()
    rows = (await db_session.execute(
        select(OutboxMessage).where(OutboxMessage.status == "pending")
    )).scalars().all()
    for row in rows:
        payload = dict(row.payload)
        msg_type = OutboundMessageType(payload.pop("type"))
        msg = OutboundMessage(
            to_phone=row.to_phone,
            type=msg_type,
            payload=payload,
            idempotency_key=row.idempotency_key,
        )
        wa_id = await provider.send(msg)
        row.status = "sent"
        row.wa_message_id = wa_id
    await db_session.commit()

    sends = provider.drain_sends()
    assert len(sends) == 1
    assert "110" in sends[0].payload.get("body", "") or "Chicken Biryani" in sends[0].payload.get("body", "")


async def test_item_collection_pipeline_direct_match(db_session, restaurant):
    """After menu_sent, sending a dish name enqueues a confirmation message."""
    await _seed_menu(db_session, restaurant.id)

    # Step 1: greeting
    greet = InboundMessage(
        wa_message_id="wamid.pipe-greet",
        from_phone="+971509000002",
        type=MessageType.TEXT,
        payload={"text": "hello"},
        restaurant_phone=restaurant.phone,
        timestamp=1717660901,
    )
    await handle_inbound(db_session, greet, restaurant_id=restaurant.id)
    await db_session.commit()

    # Step 2: order a dish
    order_msg = InboundMessage(
        wa_message_id="wamid.pipe-item1",
        from_phone="+971509000002",
        type=MessageType.TEXT,
        payload={"text": "chicken biryani"},
        restaurant_phone=restaurant.phone,
        timestamp=1717660902,
    )
    await handle_inbound(db_session, order_msg, restaurant_id=restaurant.id)
    await db_session.commit()

    rows = (await db_session.execute(select(OutboxMessage))).scalars().all()
    # Should have greeting + item confirmation
    assert len(rows) >= 2
    bodies = [r.payload.get("body", "") for r in rows]
    assert any("Chicken Biryani" in b or "110" in b for b in bodies)
