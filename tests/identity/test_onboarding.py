from decimal import Decimal

from app.identity.service import get_onboarding_status


async def test_new_signup_not_complete_without_menu(db_session, restaurant):
    restaurant.settings = {**restaurant.settings, "onboarding_complete": False}
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["complete"] is False
    assert st["has_menu"] is False


async def test_catalog_synced_false_when_dish_only_remains(db_session, restaurant):
    from app.catalog.models import CatalogProduct
    from app.menu.models import Dish, Menu

    restaurant.settings = {
        **restaurant.settings,
        "catalog_id": "CAT1",
        "onboarding_complete": False,
    }
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, name="Biryani",
        price_aed=Decimal("30"), is_available=True,
        name_normalized="biryani", catalog_retailer_id="r1",
    ))
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, name="Mint",
        price_aed=Decimal("12"), is_available=True,
        name_normalized="mint",
    ))
    db_session.add(CatalogProduct(
        restaurant_id=restaurant.id, retailer_id="r1", name="Biryani",
        price_aed=Decimal("30"), is_active=True, raw={},
    ))
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["catalog_synced"] is False
    assert st["complete"] is False


async def test_legacy_restaurant_with_menu_skips_onboarding(db_session, restaurant):
    from app.menu.models import Menu

    restaurant.settings = {k: v for k, v in restaurant.settings.items() if k != "onboarding_complete"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["complete"] is True