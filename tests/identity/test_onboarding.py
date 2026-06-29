from app.identity.service import get_onboarding_status


async def test_new_signup_not_complete_without_menu(db_session, restaurant):
    restaurant.settings = {**restaurant.settings, "onboarding_complete": False}
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["complete"] is False
    assert st["has_menu"] is False


async def test_legacy_restaurant_with_menu_skips_onboarding(db_session, restaurant):
    from app.menu.models import Menu

    restaurant.settings = {k: v for k, v in restaurant.settings.items() if k != "onboarding_complete"}
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.commit()
    st = await get_onboarding_status(db_session, restaurant=restaurant)
    assert st["complete"] is True