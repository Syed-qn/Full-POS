"""Sending the WhatsApp catalog as a multi-product message (the Cloud API way)."""
from decimal import Decimal

from sqlalchemy import select

from app.catalog.models import CatalogProduct
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
    # STRICT model: catalogue cards come ONLY from the synced Meta catalogue mirror.
    # Seed the CatalogProduct rows the "Sync from Meta" step would have created.
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="nwb4pa5fbn", name="Chicken Biryani",
        price_aed=Decimal("20.00"), currency="AED", availability="in stock",
        category="Biryani", is_active=True, raw={},
    ))
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="lemonmint01", name="Lemon Mint",
        price_aed=Decimal("12.00"), currency="AED", availability="in stock",
        category="Drinks", is_active=True, raw={},
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
    assert "text" in types  # immediate greeting ack (catalog delivery can fail async)
    assert "product_list" in types  # catalogue cards, not the full text menu dump


async def test_show_menu_sends_catalog_when_mode_on(db_session, restaurant):
    """Asking to see the menu mid-chat sends the catalogue cards, not the text list."""
    from app.conversation.engine import handle_inbound
    from app.whatsapp.port import InboundMessage, MessageType

    await _seed_linked_menu(db_session, restaurant)

    msg = InboundMessage(
        wa_message_id="wamid.menu", from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": "show me the menu"}, restaurant_phone="+97141234567",
        timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    types = [o.payload.get("type") for o in outs]
    assert "product_list" in types  # catalogue cards, not the text menu


async def test_order_again_after_completed_order_sends_catalog(db_session, restaurant):
    """A 'menu' request after a finished order (post_order) re-opens ordering with the
    CATALOGUE, not the text list."""
    from app.conversation.engine import handle_inbound
    from app.conversation.models import Conversation
    from app.whatsapp.port import InboundMessage, MessageType

    await _seed_linked_menu(db_session, restaurant)
    # Customer is in post_order (just completed an order).
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"dialogue_phase": "post_order", "dialogue_state": "post_order"},
    )
    db_session.add(conv)
    await db_session.commit()

    msg = InboundMessage(
        wa_message_id="wamid.again", from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": "menu"}, restaurant_phone="+97141234567", timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    types = [o.payload.get("type") for o in outs]
    assert "product_list" in types


async def test_show_menu_falls_back_to_text_when_catalog_off(db_session, restaurant):
    """Catalogue OFF (default): the menu surface still sends the text list as before."""
    from app.conversation.engine import handle_inbound
    from app.whatsapp.port import InboundMessage, MessageType

    # Linked dishes but catalogue mode OFF.
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Chicken Biryani",
        price_aed=Decimal("20.00"), category="Biryani", is_available=True,
        name_normalized="chicken biryani",
    ))
    await db_session.commit()

    msg = InboundMessage(
        wa_message_id="wamid.txt", from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": "show me the menu"}, restaurant_phone="+97141234567",
        timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    types = [o.payload.get("type") for o in outs]
    assert "product_list" not in types
    assert "text" in types  # the deterministic text menu


async def test_menu_request_falls_back_to_text_when_catalog_unavailable(db_session, restaurant):
    """Unified menu: menu requests prefer catalogue cards, but fall back to the real
    text menu when the catalogue can't be sent (e.g. no catalog_id configured)."""
    from app.conversation.engine import handle_inbound
    from app.whatsapp.port import InboundMessage, MessageType

    # Catalogue mode ON, dishes linked, but NO catalog_id → send_catalog returns False.
    restaurant.settings = {**restaurant.settings, "catalog_ordering_enabled": True}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Chicken Biryani",
        price_aed=Decimal("20.00"), category="Biryani", is_available=True,
        name_normalized="chicken biryani", catalog_retailer_id="abc",
    ))
    await db_session.commit()

    msg = InboundMessage(
        wa_message_id="wamid.strict", from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": "show me the menu"}, restaurant_phone="+97141234567",
        timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    bodies = [o.payload.get("body", "") for o in outs]
    types = [o.payload.get("type") for o in outs]
    assert "product_list" not in types  # catalogue couldn't send
    assert "text" in types
    assert any("Chicken Biryani" in b for b in bodies)


async def test_send_catalog_refuses_unsynced_fallback(db_session, restaurant):
    """STRICT no-fallback: catalogue mode ON with a catalog_id and dishes LINKED via
    catalog_retailer_id, but the catalogue was never synced (no CatalogProduct rows).
    send_catalog must refuse rather than leak the unsynced text-menu dishes as cards."""
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
    await db_session.commit()

    sent = await send_catalog(db_session, restaurant_id=restaurant.id, to_phone="+971501110001")
    await db_session.commit()
    assert sent is False  # refused — never falls back to text-menu dishes
    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    assert outs == []  # nothing sent at all


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


async def test_send_catalog_filters_sibling_tenant_products_in_shared_catalog(
    db_session, restaurant,
):
    """Shared Feasto mirror: product_list cards only include this tenant's dishes."""
    from app.identity.models import Restaurant

    lims = Restaurant(
        name="Lims", phone="+919344471586", password_hash="x", lat=25.0, lng=55.0,
        settings={"catalog_id": "SHARED", "catalog_ordering_enabled": True},
    )
    db_session.add(lims)
    await db_session.flush()
    b_menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    l_menu = Menu(restaurant_id=lims.id, version=1, status="active", source_files=[])
    db_session.add_all([b_menu, l_menu])
    await db_session.flush()
    b_dish = Dish(
        menu_id=b_menu.id, restaurant_id=restaurant.id, dish_number=1, name="Biryani Plate",
        price_aed=Decimal("50"), category="Rice", is_available=True,
        name_normalized="biryani plate", catalog_retailer_id="dish-biryani-1",
    )
    l_dish = Dish(
        menu_id=l_menu.id, restaurant_id=lims.id, dish_number=1, name="Lims Special",
        price_aed=Decimal("40"), category="Rice", is_available=True,
        name_normalized="lims special", catalog_retailer_id="dish-lims-1",
    )
    db_session.add_all([b_dish, l_dish])
    await db_session.flush()
    # Polluted Lims mirror: sibling Biryani row + own row (both sendable).
    db_session.add_all([
        CatalogProduct(
            restaurant_id=lims.id, retailer_id="dish-biryani-1", name="Biryani Plate",
            price_aed=Decimal("50"), currency="AED", availability="in stock",
            category="Rice", is_active=True, is_sendable=True, raw={},
        ),
        CatalogProduct(
            restaurant_id=lims.id, retailer_id="dish-lims-1", name="Lims Special",
            price_aed=Decimal("40"), currency="AED", availability="in stock",
            category="Rice", is_active=True, is_sendable=True, raw={},
        ),
    ])
    restaurant.settings = {
        **(restaurant.settings or {}),
        "catalog_id": "SHARED",
        "catalog_ordering_enabled": True,
    }
    await db_session.commit()

    sent = await send_catalog(db_session, restaurant_id=lims.id, to_phone="+971501110001")
    await db_session.commit()
    assert sent is True
    msg = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).one()
    assert msg.payload["type"] == "product_list"
    retailer_ids = {
        it["product_retailer_id"]
        for s in msg.payload["sections"] for it in s["product_items"]
    }
    assert retailer_ids == {"dish-lims-1"}
