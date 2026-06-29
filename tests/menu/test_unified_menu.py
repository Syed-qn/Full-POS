"""Unified menu merges text dishes and Meta catalogue rows with link status."""
from decimal import Decimal

from app.catalog.models import CatalogProduct
from app.menu.models import Dish, Menu
from app.menu.unified import build_unified_menu


async def _seed(db_session, restaurant):
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    linked = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=1,
        name="Chicken Biryani",
        price_aed=Decimal("22.00"),
        category="Rice",
        is_available=True,
        name_normalized="chicken biryani",
        catalog_retailer_id="rid-biryani",
    )
    text_only = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=2,
        name="Lemon Mint",
        price_aed=Decimal("12.00"),
        category="Drinks",
        is_available=True,
        name_normalized="lemon mint",
    )
    db_session.add_all([linked, text_only])
    db_session.add(
        CatalogProduct(
            restaurant_id=restaurant.id,
            retailer_id="rid-biryani",
            name="Chicken Biryani",
            price_aed=Decimal("30.00"),
            currency="AED",
            availability="in stock",
            category="Rice",
            is_active=True,
            raw={},
        )
    )
    db_session.add(
        CatalogProduct(
            restaurant_id=restaurant.id,
            retailer_id="rid-meta-only",
            name="Mango Lassi",
            price_aed=Decimal("15.00"),
            currency="AED",
            availability="in stock",
            category="Drinks",
            is_active=True,
            raw={},
        )
    )
    await db_session.commit()
    return menu


async def test_unified_menu_link_statuses(db_session, restaurant):
    await _seed(db_session, restaurant)
    out = await build_unified_menu(db_session, restaurant_id=restaurant.id, catalog_id="CAT1")
    statuses = {i.name: i.link_status for i in out.items}
    assert statuses["Chicken Biryani"] == "linked"
    assert statuses["Lemon Mint"] == "dish_only"
    assert statuses["Mango Lassi"] == "catalog_only"
    assert out.linked_count == 1
    assert out.dish_only_count == 1
    assert out.catalog_only_count == 1
    biryani = next(i for i in out.items if i.name == "Chicken Biryani")
    assert biryani.price_aed == Decimal("22.00")  # dish price, not Meta mirror