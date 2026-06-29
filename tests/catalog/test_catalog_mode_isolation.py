"""Catalogue mode must NOT leak text-menu (dish) items into the conversation.

Bug: in catalogue mode the bot answered "any drinks?" by recommending a Lemon Mint that
only exists in the text menu (not the Meta catalogue). The bot's menu knowledge, dish
descriptions, and type-ordering must all be restricted to the synced catalogue.
"""
from decimal import Decimal

from app.catalog.models import CatalogProduct
from app.conversation.engine import (
    _catalog_excludes_dish,
    _catalog_filter_candidates,
    _render_menu,
)
from app.menu.models import Dish, Menu


async def _seed(db_session, restaurant, *, catalog_mode: bool):
    restaurant.settings = {
        **restaurant.settings,
        "catalog_id": "CAT1",
        "catalog_ordering_enabled": catalog_mode,
    }
    # Catalogue (Meta) has ONLY Chicken Biryani.
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="ju9f8jfy90", name="Chicken Biryani",
        price_aed=Decimal("30.00"), currency="AED", availability="in stock",
        category="Rice", is_active=True, raw={},
    ))
    # Text menu has the biryani (linked) AND a Lemon Mint drink (NOT in the catalogue).
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    biryani = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Chicken Biryani",
        price_aed=Decimal("20.00"), category="Rice", is_available=True,
        name_normalized="chicken biryani", catalog_retailer_id="ju9f8jfy90",
    )
    mint = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Lemon Mint",
        price_aed=Decimal("12.00"), category="Drinks", is_available=True,
        name_normalized="lemon mint", description="Refreshing lemon mint, not a mojito.",
    )
    db_session.add_all([biryani, mint])
    await db_session.commit()
    return biryani, mint


async def test_menu_knowledge_is_catalogue_only(db_session, restaurant):
    await _seed(db_session, restaurant, catalog_mode=True)
    text = await _render_menu(db_session, restaurant.id)
    assert "Chicken Biryani" in text       # the catalogue item
    assert "Lemon Mint" not in text        # text-menu drink must NOT leak
    assert "AED 30" in text                # catalogue price, not the dish's AED 20


async def test_text_mode_still_lists_dishes(db_session, restaurant):
    await _seed(db_session, restaurant, catalog_mode=False)
    text = await _render_menu(db_session, restaurant.id)
    assert "Lemon Mint" in text            # text mode shows the full dish menu
    assert "Chicken Biryani" in text


async def test_catalog_excludes_dish_logic(db_session, restaurant):
    biryani, mint = await _seed(db_session, restaurant, catalog_mode=True)
    # Biryani is in the catalogue (matching active retailer_id) → allowed.
    assert await _catalog_excludes_dish(db_session, restaurant.id, biryani) is False
    # Lemon Mint has no catalogue link → excluded.
    assert await _catalog_excludes_dish(db_session, restaurant.id, mint) is True


async def test_catalog_excludes_nothing_in_text_mode(db_session, restaurant):
    biryani, mint = await _seed(db_session, restaurant, catalog_mode=False)
    # Text mode: no restriction — every dish is orderable.
    assert await _catalog_excludes_dish(db_session, restaurant.id, biryani) is False
    assert await _catalog_excludes_dish(db_session, restaurant.id, mint) is False


async def test_ambiguous_candidates_filtered_to_catalogue(db_session, restaurant):
    """A 'did you mean ...' prompt must only list catalogue items, never a text-menu dish."""
    biryani, mint = await _seed(db_session, restaurant, catalog_mode=True)
    kept = await _catalog_filter_candidates(db_session, restaurant.id, [biryani, mint])
    assert biryani in kept and mint not in kept  # Lemon Mint dropped from the options


async def test_ambiguous_candidates_unfiltered_in_text_mode(db_session, restaurant):
    biryani, mint = await _seed(db_session, restaurant, catalog_mode=False)
    kept = await _catalog_filter_candidates(db_session, restaurant.id, [biryani, mint])
    assert kept == [biryani, mint]  # text mode: keep all candidates


async def test_remove_nonctalog_item_never_named(db_session, restaurant):
    """In catalogue mode, 'remove lemon mint' (a text-menu item) must NOT echo the
    dish name back ('Lemon Mint isn't in your cart') — it leaks a non-catalogue item.
    The guard returns no_match instead."""
    from app.conversation.engine import _execute_ai_remove_item
    from app.conversation.models import Conversation
    from app.ordering.models import Customer, Order

    await _seed(db_session, restaurant, catalog_mode=True)
    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="R1-9001",
        status="draft", priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("0.00"), total=Decimal("0.00"),
    )
    db_session.add(order)
    await db_session.flush()
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"dialogue_phase": "ordering", "dialogue_state": "collecting_items",
               "draft_order_id": order.id},
    )
    db_session.add(conv)
    await db_session.commit()

    outcome, name = await _execute_ai_remove_item(
        db_session, conv, restaurant.id, "lemon mint", None
    )
    assert outcome == "no_match"   # never "not_in_cart"
    assert name is None            # never the leaked "Lemon Mint"


async def test_update_qty_nonctalog_item_never_named(db_session, restaurant):
    """In catalogue mode, 'make it 2 lemon mint' must NOT offer to add a text-menu item
    ('Lemon Mint isn't in your cart yet, want me to add 2?'). Guard returns no_match."""
    from app.conversation.engine import _execute_ai_update_qty
    from app.conversation.models import Conversation
    from app.ordering.models import Customer, Order
    from app.whatsapp.port import InboundMessage, MessageType

    await _seed(db_session, restaurant, catalog_mode=True)
    customer = Customer(
        restaurant_id=restaurant.id, phone="+971501110001", name="Ali",
        usual_order_times={}, tags={}, total_orders=0, total_spend=Decimal("0.00"),
    )
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id, customer_id=customer.id, order_number="R1-9002",
        status="draft", priority="normal", weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"), subtotal=Decimal("0.00"), total=Decimal("0.00"),
    )
    db_session.add(order)
    await db_session.flush()
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"dialogue_phase": "ordering", "dialogue_state": "collecting_items",
               "draft_order_id": order.id},
    )
    db_session.add(conv)
    await db_session.commit()

    inbound = InboundMessage(
        wa_message_id="wamid.mq", from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": "make it 2 lemon mint"}, restaurant_phone="+97141234567",
        timestamp=1717660800,
    )
    outcome, name = await _execute_ai_update_qty(
        db_session, conv, inbound, restaurant.id, "lemon mint", 2
    )
    assert outcome == "no_match"   # never "not_in_cart"
    assert name is None            # never the leaked "Lemon Mint"


async def test_catalog_typed_order_adds_directly_not_catalogue(db_session, restaurant):
    """In catalogue mode, typing 'one chicken biryani' (a catalogue dish) must ADD it to
    the cart deterministically, NOT re-send the catalogue cards. Regression: the model
    sometimes classified a typed order as a menu request and pushed the catalogue with no
    text reply, so a typed order silently did nothing."""
    from app.conversation.engine import handle_inbound
    from app.conversation.models import Conversation
    from app.ordering.models import OrderItem
    from app.outbox.models import OutboxMessage
    from app.whatsapp.port import InboundMessage, MessageType
    from sqlalchemy import select

    await _seed(db_session, restaurant, catalog_mode=True)
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"dialogue_phase": "ordering", "dialogue_state": "menu_sent"},
    )
    db_session.add(conv)
    await db_session.commit()

    msg = InboundMessage(
        wa_message_id="wamid.typed1", from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": "one chicken biryani"}, restaurant_phone="+97141234567",
        timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    items = (await db_session.scalars(select(OrderItem))).all()
    assert len(items) == 1 and items[0].dish_name == "Chicken Biryani"  # added directly
    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
    )).all()
    types = [o.payload.get("type") for o in outs]
    assert "product_list" not in types  # did NOT re-send the catalogue cards
    assert any("Added" in (o.payload.get("body", "") or "") for o in outs)  # got a text reply


async def test_catalog_typed_noncatalogue_item_falls_through(db_session, restaurant):
    """A typed item NOT in the catalogue (Lemon Mint) must NOT be added by the
    deterministic catalogue interceptor — it returns False so the AI gives the honest
    'we don't have it' reply (no text-menu leak, no silent add)."""
    from app.conversation.engine import _try_catalog_typed_order
    from app.conversation.models import Conversation
    from app.identity.models import Restaurant
    from app.whatsapp.port import InboundMessage, MessageType

    await _seed(db_session, restaurant, catalog_mode=True)
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110002", counterpart="customer",
        state={"dialogue_phase": "ordering", "dialogue_state": "menu_sent"},
    )
    db_session.add(conv)
    await db_session.commit()
    rest = await db_session.get(Restaurant, restaurant.id)

    for text in ("one lemon mint", "what is chicken biryani", "done", "menu"):
        msg = InboundMessage(
            wa_message_id=f"wamid.{text.replace(' ', '_')}", from_phone="+971501110002",
            type=MessageType.TEXT, payload={"text": text},
            restaurant_phone="+97141234567", timestamp=1717660800,
        )
        handled = await _try_catalog_typed_order(
            db_session, conv, msg, restaurant.id, rest
        )
        assert handled is False, f"{text!r} should fall through to the AI, not be intercepted"


def test_is_cart_query_detection():
    """Cart queries are detected; edits/cancels/menu are NOT (they are real actions)."""
    from app.conversation.engine import _is_cart_query

    for yes in ("what's in my cart", "whats in my cart now", "show my cart", "my cart",
                "what's in my order", "show my order", "what did i order"):
        assert _is_cart_query(yes) is True, yes
    for no in ("cancel my order", "clear cart", "empty my cart", "add to cart",
               "add 2 biryani", "menu", "one chicken biryani", "hi"):
        assert _is_cart_query(no) is False, no


async def test_cart_query_shows_cart_not_catalogue(db_session, restaurant):
    """'What's in my cart' must show the REAL cart deterministically, never re-send the
    catalogue cards (the model used to mishandle it in catalogue mode)."""
    from app.conversation.engine import handle_inbound
    from app.conversation.models import Conversation
    from app.menu.models import Dish
    from app.outbox.models import OutboxMessage
    from app.ordering.service import add_item, create_draft_order, get_or_create_customer
    from app.whatsapp.port import InboundMessage, MessageType
    from sqlalchemy import select

    await _seed(db_session, restaurant, catalog_mode=True)
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971501110003"
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    biryani = await db_session.scalar(
        select(Dish).where(Dish.name == "Chicken Biryani")
    )
    await add_item(db_session, order=order, dish=biryani, qty=1)
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110003", counterpart="customer",
        state={"dialogue_phase": "ordering", "dialogue_state": "menu_sent",
               "draft_order_id": order.id},
    )
    db_session.add(conv)
    await db_session.commit()

    msg = InboundMessage(
        wa_message_id="wamid.cartq", from_phone="+971501110003", type=MessageType.TEXT,
        payload={"text": "whats in my cart now"}, restaurant_phone="+97141234567",
        timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    outs = (await db_session.scalars(
        select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110003")
    )).all()
    types = [o.payload.get("type") for o in outs]
    bodies = [o.payload.get("body", "") or "" for o in outs]
    assert "product_list" not in types                       # no catalogue re-send
    assert any("cart" in b.lower() and "Chicken Biryani" in b for b in bodies)


async def test_what_is_nonctalog_item_never_describes_it(db_session, restaurant):
    """'what is <text-menu item>' in catalogue mode must NEVER return the dish's stored
    description/price — the catalogue dish-info guard returns None, so the bot can't talk
    up a non-catalogue item (it falls through to the catalogue-bounded AI)."""
    from app.conversation.engine import handle_inbound
    from app.conversation.models import Conversation
    from app.ordering.models import OrderItem
    from app.outbox.models import OutboxMessage
    from app.whatsapp.port import InboundMessage, MessageType
    from sqlalchemy import select

    await _seed(db_session, restaurant, catalog_mode=True)
    conv = Conversation(
        restaurant_id=restaurant.id, phone="+971501110001", counterpart="customer",
        state={"dialogue_phase": "ordering", "dialogue_state": "collecting_items"},
    )
    db_session.add(conv)
    await db_session.commit()

    msg = InboundMessage(
        wa_message_id="wamid.whatis", from_phone="+971501110001", type=MessageType.TEXT,
        payload={"text": "what is lemon mint"}, restaurant_phone="+97141234567",
        timestamp=1717660800,
    )
    await handle_inbound(db_session, msg, restaurant_id=restaurant.id)
    await db_session.commit()

    bodies = [
        o.payload.get("body", "")
        for o in (await db_session.scalars(
            select(OutboxMessage).where(OutboxMessage.to_phone == "+971501110001")
        )).all()
    ]
    # The Lemon Mint stored description / price must NOT appear anywhere.
    assert not any("refreshing" in b.lower() or "mojito" in b.lower() for b in bodies)
    assert not any("AED 12" in b for b in bodies)
    # And it certainly wasn't added to the cart.
    items = (await db_session.scalars(select(OrderItem))).all()
    assert all(getattr(it, "dish_name", "") != "Lemon Mint" for it in items)
