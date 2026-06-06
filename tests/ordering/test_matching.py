from decimal import Decimal
from app.ordering.matching import normalize_name, find_dish_matches


def test_normalize_name_lowercases_and_strips():
    assert normalize_name("  Chicken BIRYANI  ") == "chicken biryani"


def test_normalize_name_removes_punctuation():
    assert normalize_name("Chkn. Biryani!") == "chkn biryani"


def test_normalize_name_preserves_arabic():
    """Unicode word chars survive normalization (regression: Arabic was dropped)."""
    assert normalize_name("برياني دجاج") == "برياني دجاج"


def test_normalize_name_preserves_arabic_with_punctuation():
    """Punctuation around an Arabic name becomes collapsed spaces, name intact."""
    assert normalize_name("  برياني، دجاج!  ") == "برياني دجاج"


async def test_find_dish_matches_arabic_dish(db_session, restaurant):
    """An Arabic-named dish is findable via fuzzy trigram query (pg_trgm bytewise)."""
    from app.ordering.matching import MatchConfidence
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id,
        dish_number=410, name="برياني دجاج",
        price_aed=Decimal("22.00"), category="Rice", is_available=True,
        name_normalized=normalize_name("برياني دجاج"),
    )
    db_session.add(dish)
    await db_session.commit()

    results = await find_dish_matches(
        db_session, restaurant_id=restaurant.id, query="برياني دجاج",
    )
    assert results.confidence == MatchConfidence.DIRECT
    assert len(results.candidates) == 1
    assert results.candidates[0].dish_number == 410


async def test_find_dish_matches_single_strong_match(db_session, restaurant):
    """Single match above 0.6 with gap > 0.15 → MatchResult.DIRECT."""
    from app.ordering.matching import MatchConfidence
    # Seed an active menu with one dish
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id,
        dish_number=110, name="Chicken Biryani",
        price_aed=Decimal("22.00"), category="Rice", is_available=True,
        name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.commit()

    results = await find_dish_matches(db_session, restaurant_id=restaurant.id, query="chikn biryani")
    assert results.confidence == MatchConfidence.DIRECT
    assert len(results.candidates) == 1
    assert results.candidates[0].dish_number == 110


async def test_find_dish_matches_by_exact_number(db_session, restaurant):
    from app.ordering.matching import MatchConfidence
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id,
        dish_number=201, name="Mutton Karahi",
        price_aed=Decimal("35.00"), category="Curries", is_available=True,
        name_normalized="mutton karahi",
    )
    db_session.add(dish)
    await db_session.commit()

    results = await find_dish_matches(db_session, restaurant_id=restaurant.id, query="201")
    assert results.confidence == MatchConfidence.DIRECT
    assert results.candidates[0].dish_number == 201


async def test_find_dish_matches_none_returns_no_match(db_session, restaurant):
    from app.ordering.matching import MatchConfidence
    from app.menu.models import Dish, Menu
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    db_session.add(Dish(
        menu_id=menu.id, restaurant_id=restaurant.id,
        dish_number=301, name="Mango Lassi",
        price_aed=Decimal("10.00"), category="Drinks", is_available=True,
        name_normalized="mango lassi",
    ))
    await db_session.commit()

    results = await find_dish_matches(db_session, restaurant_id=restaurant.id, query="xyz zyx zzz")
    assert results.confidence == MatchConfidence.NO_MATCH
    assert results.candidates == []
