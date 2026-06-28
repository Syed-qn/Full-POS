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
