"""Menu/catalog keyword requests must not hijack mid-checkout phases."""
from decimal import Decimal

from sqlalchemy import select

from app.conversation.engine import handle_inbound
from app.conversation.models import Conversation
from app.conversation.service import get_or_create_conversation
from app.menu.models import Dish, Menu
from app.outbox.models import OutboxMessage
from app.whatsapp.port import InboundMessage, MessageType


async def _seed_catalog_menu(db_session, restaurant):
    restaurant.settings = {
        **(restaurant.settings or {}),
        "catalog_id": "TEST-CAT-001",
        "catalog_ordering_enabled": True,
    }
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    from app.catalog.models import CatalogProduct

    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1,
        name="Chicken Biryani", price_aed=Decimal("20.00"), category="Biryani",
        is_available=True, catalog_retailer_id="ret-1",
    ))
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="ret-1", name="Chicken Biryani",
        price_aed=Decimal("20.00"), currency="AED", availability="in stock",
        category="Biryani", is_active=True, is_sendable=True, raw={},
    ))
    await db_session.commit()


def _text_inbound(text: str, *, wa_id: str = "wamid.midflow") -> InboundMessage:
    return InboundMessage(
        wa_message_id=wa_id,
        from_phone="+971501110001",
        type=MessageType.TEXT,
        payload={"text": text},
        restaurant_phone="+97141234567",
        timestamp=1717660800,
    )


async def test_menu_keyword_blocked_during_address_capture(db_session, restaurant):
    await _seed_catalog_menu(db_session, restaurant)
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
    )
    conv.state = {"dialogue_phase": "address_capture", "dialogue_state": "address_capture"}
    await db_session.commit()

    await handle_inbound(
        db_session, _text_inbound("order"), restaurant_id=restaurant.id,
    )
    await db_session.commit()

    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    types = [o.payload.get("type") for o in outs]
    assert "product_list" not in types, f"catalog hijacked address_capture: {types}"


async def test_menu_keyword_blocked_during_awaiting_confirmation(db_session, restaurant):
    await _seed_catalog_menu(db_session, restaurant)
    conv = await get_or_create_conversation(
        db_session, restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
    )
    conv.state = {
        "dialogue_phase": "awaiting_confirmation",
        "dialogue_state": "order_confirmation",
        "pending_order_id": 999,
    }
    await db_session.commit()

    await handle_inbound(
        db_session, _text_inbound("menu", wa_id="wamid.confirm-menu"), restaurant_id=restaurant.id,
    )
    await db_session.commit()

    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    types = [o.payload.get("type") for o in outs]
    assert "product_list" not in types, f"catalog hijacked confirmation: {types}"
    # Phase unchanged — checkout not derailed.
    conv = await db_session.scalar(
        select(Conversation).where(Conversation.id == conv.id)
    )
    assert conv.state.get("dialogue_phase") == "awaiting_confirmation"