from datetime import date, datetime, time
from decimal import Decimal

import pytest

from app.menu.pricing import create_price_rule, resolve_dish_price


@pytest.mark.anyio
async def test_no_rules_falls_back_to_base_price(db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()

    price = await resolve_dish_price(
        db_session, dish_id=dish.id, at=datetime(2026, 7, 8, 12, 0), channel=None,
    )
    assert price == dish.price_aed


@pytest.mark.anyio
async def test_time_rule_matches_within_window(db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()

    await create_price_rule(
        db_session, restaurant_id=restaurant.id, dish_id=dish.id, rule_type="time",
        price_aed=Decimal("15.00"), start_time=time(17, 0), end_time=time(19, 0),
    )
    await db_session.commit()

    inside = await resolve_dish_price(
        db_session, dish_id=dish.id, at=datetime(2026, 7, 8, 18, 0), channel=None,
    )
    outside = await resolve_dish_price(
        db_session, dish_id=dish.id, at=datetime(2026, 7, 8, 20, 0), channel=None,
    )
    assert inside == Decimal("15.00")
    assert outside == dish.price_aed


@pytest.mark.anyio
async def test_time_rule_respects_day_of_week(db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()

    # 2026-07-08 is a Wednesday (weekday() == 2); restrict rule to weekends only.
    await create_price_rule(
        db_session, restaurant_id=restaurant.id, dish_id=dish.id, rule_type="time",
        price_aed=Decimal("15.00"), start_time=time(0, 0), end_time=time(23, 59),
        days_of_week=[4, 5],
    )
    await db_session.commit()

    price = await resolve_dish_price(
        db_session, dish_id=dish.id, at=datetime(2026, 7, 8, 12, 0), channel=None,
    )
    assert price == dish.price_aed
    assert date(2026, 7, 8).weekday() == 2


@pytest.mark.anyio
async def test_channel_rule_matches_channel(db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()

    await create_price_rule(
        db_session, restaurant_id=restaurant.id, dish_id=dish.id, rule_type="channel",
        price_aed=Decimal("22.00"), channel="aggregator",
    )
    await db_session.commit()

    aggregator_price = await resolve_dish_price(
        db_session, dish_id=dish.id, at=datetime(2026, 7, 8, 12, 0), channel="aggregator",
    )
    delivery_price = await resolve_dish_price(
        db_session, dish_id=dish.id, at=datetime(2026, 7, 8, 12, 0), channel="delivery",
    )
    assert aggregator_price == Decimal("22.00")
    assert delivery_price == dish.price_aed


@pytest.mark.anyio
async def test_first_matching_rule_wins(db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()

    await create_price_rule(
        db_session, restaurant_id=restaurant.id, dish_id=dish.id, rule_type="branch",
        price_aed=Decimal("18.00"),
    )
    await create_price_rule(
        db_session, restaurant_id=restaurant.id, dish_id=dish.id, rule_type="branch",
        price_aed=Decimal("99.00"),
    )
    await db_session.commit()

    price = await resolve_dish_price(
        db_session, dish_id=dish.id, at=datetime(2026, 7, 8, 12, 0), channel=None,
    )
    assert price == Decimal("18.00")


@pytest.mark.anyio
async def test_invalid_rule_type_rejected(db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()

    with pytest.raises(ValueError):
        await create_price_rule(
            db_session, restaurant_id=restaurant.id, dish_id=dish.id, rule_type="bogus",
            price_aed=Decimal("1.00"),
        )


@pytest.mark.anyio
async def test_create_and_get_effective_price_via_router(client, db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.identity.auth import create_access_token
    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()
    auth_headers = {"Authorization": f"Bearer {create_access_token(restaurant_id=restaurant.id)}"}

    create_resp = await client.post(
        f"/api/v1/dishes/{dish.id}/price-rules",
        json={"rule_type": "channel", "price_aed": "25.00", "channel": "aggregator"},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    assert create_resp.json()["price_aed"] == "25.00"

    price_resp = await client.get(
        f"/api/v1/dishes/{dish.id}/effective-price?channel=aggregator", headers=auth_headers,
    )
    assert price_resp.status_code == 200
    assert price_resp.json()["price_aed"] == "25.00"

    base_resp = await client.get(
        f"/api/v1/dishes/{dish.id}/effective-price", headers=auth_headers,
    )
    assert base_resp.status_code == 200
    assert base_resp.json()["price_aed"] == str(dish.price_aed)


@pytest.mark.anyio
async def test_effective_price_endpoint_404_for_other_restaurant_dish(client, db_session, restaurant, seed_biryani_menu):
    from sqlalchemy import select

    from app.identity.auth import create_access_token
    from app.identity.models import Restaurant
    from app.menu.models import Dish

    dish = (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.name == "Chicken Biryani")
    )).one()

    other = Restaurant(
        name="Other", phone="+971500000999", password_hash="x",
        lat=25.2, lng=55.2, settings={},
    )
    db_session.add(other)
    await db_session.flush()
    await db_session.commit()
    other_token = create_access_token(restaurant_id=other.id)

    resp = await client.get(
        f"/api/v1/dishes/{dish.id}/effective-price",
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert resp.status_code == 404
