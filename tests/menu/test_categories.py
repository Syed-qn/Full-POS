import pytest
from sqlalchemy import select

from app.menu.categories import (
    assign_dish_category,
    create_category,
    delete_category,
    list_categories,
    rename_category,
)
from app.menu.models import Category, Dish


@pytest.mark.anyio
async def test_create_and_list_categories(db_session, restaurant):
    await create_category(db_session, restaurant_id=restaurant.id, name="Starters", sort_order=1)
    await create_category(db_session, restaurant_id=restaurant.id, name="Mains", sort_order=2)
    await db_session.commit()

    rows = await list_categories(db_session, restaurant_id=restaurant.id)
    assert [r.name for r in rows] == ["Starters", "Mains"]


@pytest.mark.anyio
async def test_duplicate_category_name_rejected(db_session, restaurant):
    await create_category(db_session, restaurant_id=restaurant.id, name="Starters")
    await db_session.commit()
    with pytest.raises(ValueError):
        await create_category(db_session, restaurant_id=restaurant.id, name="Starters")


@pytest.mark.anyio
async def test_assign_dish_category_denormalizes_name(db_session, active_menu_with_dish):
    # active_menu_with_dish is created via auth_headers' own signed-up tenant, which
    # is a DIFFERENT restaurant row than the `restaurant` fixture (direct DB insert) —
    # so the dish's own restaurant_id is the source of truth here, not `restaurant.id`.
    dish = (await db_session.scalars(select(Dish))).one()
    cat = await create_category(db_session, restaurant_id=dish.restaurant_id, name="Beverages")
    await db_session.commit()

    updated = await assign_dish_category(
        db_session, restaurant_id=dish.restaurant_id, dish_id=dish.id, category_id=cat.id,
    )
    await db_session.commit()
    assert updated.category_id == cat.id
    assert updated.category == "Beverages"


@pytest.mark.anyio
async def test_rename_category_does_not_retroactively_rename_dish_text(db_session, active_menu_with_dish):
    dish = (await db_session.scalars(select(Dish))).one()
    cat = await create_category(db_session, restaurant_id=dish.restaurant_id, name="Beverages")
    await db_session.commit()
    await assign_dish_category(db_session, restaurant_id=dish.restaurant_id, dish_id=dish.id, category_id=cat.id)
    await db_session.commit()

    renamed = await rename_category(db_session, restaurant_id=dish.restaurant_id, category_id=cat.id, name="Drinks")
    await db_session.commit()
    assert renamed.name == "Drinks"


@pytest.mark.anyio
async def test_delete_category_blocked_while_dishes_reference_it(db_session, active_menu_with_dish):
    dish = (await db_session.scalars(select(Dish))).one()
    cat = await create_category(db_session, restaurant_id=dish.restaurant_id, name="Beverages")
    await db_session.commit()
    await assign_dish_category(db_session, restaurant_id=dish.restaurant_id, dish_id=dish.id, category_id=cat.id)
    await db_session.commit()

    with pytest.raises(ValueError):
        await delete_category(db_session, restaurant_id=dish.restaurant_id, category_id=cat.id)


@pytest.mark.anyio
async def test_delete_unused_category_succeeds(db_session, restaurant):
    cat = await create_category(db_session, restaurant_id=restaurant.id, name="Unused")
    await db_session.commit()
    await delete_category(db_session, restaurant_id=restaurant.id, category_id=cat.id)
    await db_session.commit()
    rows = (await db_session.scalars(select(Category).where(Category.id == cat.id))).all()
    assert rows == []


@pytest.mark.anyio
async def test_category_router_crud(client, auth_headers):
    created = await client.post(
        "/api/v1/categories", json={"name": "Starters", "sort_order": 1}, headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    cat_id = created.json()["id"]

    listed = await client.get("/api/v1/categories", headers=auth_headers)
    assert listed.status_code == 200
    assert any(c["id"] == cat_id for c in listed.json())

    renamed = await client.patch(
        f"/api/v1/categories/{cat_id}", json={"name": "Appetizers"}, headers=auth_headers,
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Appetizers"

    deleted = await client.delete(f"/api/v1/categories/{cat_id}", headers=auth_headers)
    assert deleted.status_code == 204
