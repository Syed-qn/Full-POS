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
        name_normalized="lemon mint",
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
