"""Sending the WhatsApp catalog as a multi-product message (the Cloud API way)."""
from decimal import Decimal

from sqlalchemy import select

from app.catalog.service import send_catalog
from app.menu.models import Dish, Menu
from app.outbox.models import OutboxMessage
from app.whatsapp.cloud_provider import _build_graph_payload
from app.whatsapp.port import OutboundMessage, OutboundMessageType


async def _seed_linked_menu(db_session, restaurant):
    restaurant.settings = {**restaurant.settings, "catalog_id": "1528685515412822",
                           "catalog_ordering_enabled": True}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Chicken Biryani",
        price_aed=Decimal("20.00"), category="Biryani", is_available=True,
        name_normalized="chicken biryani", catalog_retailer_id="nwb4pa5fbn",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Lemon Mint",
        price_aed=Decimal("12.00"), category="Drinks", is_available=True,
        name_normalized="lemon mint", catalog_retailer_id="lemonmint01",
    ))
    await db_session.commit()


def test_provider_builds_product_list_payload():
    msg = OutboundMessage(
        to_phone="+971501110001",
        type=OutboundMessageType.PRODUCT_LIST,
        payload={
            "header": "Our Menu", "body": "Tap to add",
            "catalog_id": "1528685515412822",
            "sections": [{"title": "Biryani", "product_items": [{"product_retailer_id": "nwb4pa5fbn"}]}],
        },
        idempotency_key="t-1",
    )
    p = _build_graph_payload(msg)
    assert p["type"] == "interactive"
    assert p["interactive"]["type"] == "product_list"
    assert p["interactive"]["action"]["catalog_id"] == "1528685515412822"
    assert p["interactive"]["action"]["sections"][0]["product_items"][0][
        "product_retailer_id"] == "nwb4pa5fbn"


async def test_send_catalog_groups_by_category(db_session, restaurant):
    await _seed_linked_menu(db_session, restaurant)
    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone="+971501110001")
    await db_session.commit()
    assert sent is True
    msg = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).one()
    sections = msg.payload["sections"]
    titles = {s["title"] for s in sections}
    assert titles == {"Biryani", "Drinks"}
    assert msg.payload["catalog_id"] == "1528685515412822"


async def test_greeting_sends_catalog_when_mode_on(db_session, restaurant):
    """With catalogue mode on, a greeting sends the product cards instead of the text menu."""
    from app.conversation.engine import handle_inbound
    from app.whatsapp.port import InboundMessage, MessageType

    await _seed_linked_menu(db_session, restaurant)

    msg = InboundMessage(
        wa_message_id="wamid.hi", from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": "hi"}, restaurant_phone="+97141234567", timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    types = [o.payload.get("type") for o in outs]
    assert "product_list" in types  # catalogue cards, not the text menu


async def test_send_catalog_noop_without_catalog_id(db_session, restaurant):
    # linked dishes but no catalog_id configured → nothing sent
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="X",
        price_aed=Decimal("5.00"), category="C", is_available=True,
        name_normalized="x", catalog_retailer_id="abc",
    ))
    await db_session.commit()
    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone="+971501110001")
    assert sent is False
