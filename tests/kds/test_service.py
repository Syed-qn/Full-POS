import pytest

from app.kds.models import CategoryStationDefault, KitchenStation
from app.kds.service import resolve_station


@pytest.mark.anyio
async def test_resolve_station_uses_dish_override_first(db_session, restaurant):
    grill = KitchenStation(restaurant_id=restaurant.id, name="Grill")
    cold = KitchenStation(restaurant_id=restaurant.id, name="Cold")
    db_session.add_all([grill, cold])
    await db_session.flush()
    db_session.add(CategoryStationDefault(restaurant_id=restaurant.id, category="Mains", station_id=cold.id))
    await db_session.commit()

    class FakeDish:
        station_id = grill.id
        category = "Mains"

    result = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    assert result == grill.id  # dish override wins over category default


@pytest.mark.anyio
async def test_resolve_station_falls_back_to_category_default(db_session, restaurant):
    cold = KitchenStation(restaurant_id=restaurant.id, name="Cold")
    db_session.add(cold)
    await db_session.flush()
    db_session.add(CategoryStationDefault(restaurant_id=restaurant.id, category="Salads", station_id=cold.id))
    await db_session.commit()

    class FakeDish:
        station_id = None
        category = "Salads"

    result = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    assert result == cold.id


@pytest.mark.anyio
async def test_resolve_station_falls_back_to_main_when_nothing_configured(db_session, restaurant):
    class FakeDish:
        station_id = None
        category = "Unmapped Category"

    result = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    main = await db_session.get(KitchenStation, result)
    assert main.name == "Main"


@pytest.mark.anyio
async def test_resolve_station_reuses_existing_main_station(db_session, restaurant):
    class FakeDish:
        station_id = None
        category = None

    first = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    second = await resolve_station(db_session, restaurant_id=restaurant.id, dish=FakeDish())
    assert first == second  # doesn't create a duplicate "Main" station each call
