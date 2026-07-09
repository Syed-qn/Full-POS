"""Category 3 — full menu control wiring tests."""

from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest
from app.menu.categories import create_category
from app.menu.models import Dish, Menu, MenuSellRule
from app.menu.modifier_service import ForcedModifierError, create_group, create_modifier, validate_forced_modifiers
from app.menu.pricing import create_price_rule, resolve_dish_price
from app.menu.service import is_dish_currently_available
from app.menu.upsell import compute_co_purchase_scores
from app.ordering.models import Customer, Order
from app.ordering.service import add_item


async def _menu_dish(db_session, restaurant, **kwargs):
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=kwargs.pop("dish_number", 1),
        name=kwargs.pop("name", "Test Dish"),
        price_aed=kwargs.pop("price_aed", Decimal("30.00")),
        category=kwargs.pop("category", "Mains"),
        is_available=True,
        name_normalized="test dish",
        **kwargs,
    )
    db_session.add(dish)
    await db_session.flush()
    return menu, dish


@pytest.mark.anyio
async def test_subcategory_parent(db_session, restaurant):
    parent = await create_category(db_session, restaurant_id=restaurant.id, name="Mains")
    child = await create_category(
        db_session, restaurant_id=restaurant.id, name="Grills", parent_id=parent.id
    )
    assert child.parent_id == parent.id


@pytest.mark.anyio
async def test_channel_and_seasonal_and_countdown(db_session, restaurant):
    _, dish = await _menu_dish(
        db_session,
        restaurant,
        channels_allowed=["delivery"],
        available_from=date.today() - timedelta(days=1),
        available_until=date.today() + timedelta(days=1),
        stock_remaining=2,
    )
    assert is_dish_currently_available(dish, today=date.today(), channel="delivery")
    assert not is_dish_currently_available(dish, today=date.today(), channel="dine_in")
    dish.stock_remaining = 0
    assert not is_dish_currently_available(dish, today=date.today(), channel="delivery")


@pytest.mark.anyio
async def test_happy_hour_price_applied_on_add_item(db_session, restaurant):
    menu, dish = await _menu_dish(db_session, restaurant, price_aed=Decimal("40.00"))
    # Always-matching time window for now (full day)
    await create_price_rule(
        db_session,
        restaurant_id=restaurant.id,
        dish_id=dish.id,
        rule_type="time",
        price_aed=Decimal("25.00"),
        start_time=time(0, 0),
        end_time=time(23, 59),
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500003301", name="P")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C3-1",
        status="draft",
        order_type="delivery",
        subtotal=Decimal("0"),
        total=Decimal("0"),
    )
    db_session.add(order)
    await db_session.flush()
    item = await add_item(
        db_session, order=order, dish=dish, qty=1, skip_modifier_validation=True
    )
    assert item.price_aed == Decimal("25.00")


@pytest.mark.anyio
async def test_channel_price_and_branch_rule(db_session, restaurant):
    _, dish = await _menu_dish(db_session, restaurant, price_aed=Decimal("50.00"))
    await create_price_rule(
        db_session,
        restaurant_id=restaurant.id,
        dish_id=dish.id,
        rule_type="channel",
        price_aed=Decimal("60.00"),
        channel="aggregator",
    )
    p = await resolve_dish_price(
        db_session,
        dish_id=dish.id,
        at=datetime.now(timezone.utc),
        channel="aggregator",
    )
    assert p == Decimal("60.00")
    await create_price_rule(
        db_session,
        restaurant_id=restaurant.id,
        dish_id=dish.id,
        rule_type="branch",
        price_aed=Decimal("55.00"),
        branch_id=restaurant.id,
    )
    # First matching rule wins — channel rule was created first for aggregator;
    # for delivery without channel match, branch may match after channel fails.
    p2 = await resolve_dish_price(
        db_session,
        dish_id=dish.id,
        at=datetime.now(timezone.utc),
        channel="delivery",
        branch_id=restaurant.id,
    )
    assert p2 == Decimal("55.00")


@pytest.mark.anyio
async def test_forced_modifiers_enforced(db_session, restaurant):
    _, dish = await _menu_dish(db_session, restaurant)
    group = await create_group(
        db_session,
        restaurant_id=restaurant.id,
        dish_id=dish.id,
        name="Spice",
        min_select=1,
        max_select=1,
        required=True,
    )
    mod = await create_modifier(
        db_session, group_id=group.id, name="Hot", price_delta_aed=Decimal("0")
    )
    with pytest.raises(ForcedModifierError):
        await validate_forced_modifiers(
            db_session, dish_id=dish.id, selected_modifier_ids=[]
        )
    await validate_forced_modifiers(
        db_session, dish_id=dish.id, selected_modifier_ids=[mod.id]
    )


@pytest.mark.anyio
async def test_stock_countdown_auto_hide(db_session, restaurant):
    _, dish = await _menu_dish(
        db_session, restaurant, stock_remaining=1, auto_hide_when_oos=True
    )
    cust = Customer(restaurant_id=restaurant.id, phone="+971500003302", name="S")
    db_session.add(cust)
    await db_session.flush()
    order = Order(
        restaurant_id=restaurant.id,
        customer_id=cust.id,
        order_number="C3-2",
        status="draft",
        subtotal=Decimal("0"),
        total=Decimal("0"),
    )
    db_session.add(order)
    await db_session.flush()
    await add_item(db_session, order=order, dish=dish, qty=1, skip_modifier_validation=True)
    await db_session.refresh(dish)
    assert dish.stock_remaining == 0
    assert dish.is_available is False


@pytest.mark.anyio
async def test_configured_upsell_rule(db_session, restaurant):
    menu, trigger = await _menu_dish(db_session, restaurant, dish_number=10, name="Burger")
    suggest = Dish(
        menu_id=menu.id,
        restaurant_id=restaurant.id,
        dish_number=11,
        name="Fries",
        price_aed=Decimal("10"),
        is_available=True,
        name_normalized="fries",
    )
    db_session.add(suggest)
    await db_session.flush()
    db_session.add(
        MenuSellRule(
            restaurant_id=restaurant.id,
            rule_kind="upsell",
            trigger_dish_id=trigger.id,
            suggest_dish_id=suggest.id,
            message="Add fries?",
        )
    )
    await db_session.flush()
    scores = await compute_co_purchase_scores(
        db_session, restaurant_id=restaurant.id, dish_ids=[trigger.id], limit=3
    )
    assert scores
    assert scores[0]["dish_id"] == suggest.id
    assert scores[0]["source"] == "upsell"


@pytest.mark.anyio
async def test_bulk_price_and_csv_router(client, auth_headers, db_session):
    r = await client.post(
        "/api/v1/menus/blank", headers=auth_headers
    )
    assert r.status_code in (200, 201)
    menu = r.json()
    menu_id = menu["id"]
    add = await client.post(
        f"/api/v1/menus/{menu_id}/dishes",
        headers=auth_headers,
        json={
            "dish_number": 1,
            "name": "Bulk Item",
            "price_aed": "20.00",
            "allergens": ["nuts"],
            "name_ar": "عنصر",
            "channels_allowed": ["delivery"],
            "stock_remaining": 5,
            "auto_hide_when_oos": True,
        },
    )
    assert add.status_code == 201, add.text
    dish_id = add.json()["id"]
    assert add.json()["allergens"] == ["nuts"]
    assert add.json()["name_ar"] == "عنصر"

    bulk = await client.post(
        f"/api/v1/menus/{menu_id}/bulk-price-update",
        headers=auth_headers,
        json={"dish_ids": [dish_id], "percent_delta": "10"},
    )
    assert bulk.status_code == 200
    assert bulk.json()["updated"] == 1

    csv_body = (
        "dish_number,name,price_aed,category,allergens,channels_allowed,stock_remaining\n"
        "2,CSV Dish,15.00,Sides,dairy|gluten,qr|dine_in,3\n"
    )
    imp = await client.post(
        f"/api/v1/menus/{menu_id}/bulk-csv-import",
        headers=auth_headers,
        files={"file": ("menu.csv", csv_body.encode(), "text/csv")},
    )
    assert imp.status_code == 200, imp.text
    assert imp.json()["created"] == 1

    cat = await client.post(
        "/api/v1/categories",
        headers=auth_headers,
        json={"name": "Parent Cat"},
    )
    assert cat.status_code == 201
    sub = await client.post(
        "/api/v1/categories",
        headers=auth_headers,
        json={"name": "Child Cat", "parent_id": cat.json()["id"]},
    )
    assert sub.status_code == 201
    assert sub.json()["parent_id"] == cat.json()["id"]

    sell = await client.post(
        "/api/v1/menus/sell-rules",
        headers=auth_headers,
        json={
            "rule_kind": "cross_sell",
            "trigger_dish_id": dish_id,
            "suggest_dish_id": dish_id,
            "message": "double up?",
        },
    )
    assert sell.status_code == 201
