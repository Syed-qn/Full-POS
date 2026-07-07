from decimal import Decimal

import pytest

from app.menu.upsell import compute_co_purchase_scores


def _token_for(restaurant_id: int) -> str:
    from app.identity.auth import create_access_token

    return create_access_token(restaurant_id=restaurant_id)


async def _make_order(db_session, restaurant, cust, order_number, status, dish_items):
    """dish_items: list of (dish, qty) tuples."""
    from app.ordering.models import Order, OrderItem

    order = Order(
        restaurant_id=restaurant.id, customer_id=cust.id, order_number=order_number,
        status=status, subtotal=Decimal("10.00"), total=Decimal("10.00"),
    )
    db_session.add(order)
    await db_session.flush()
    for dish, qty in dish_items:
        db_session.add(OrderItem(
            order_id=order.id, dish_id=dish.id, dish_number=dish.dish_number,
            dish_name=dish.name, price_aed=dish.price_aed or Decimal("10.00"), qty=qty,
        ))
    await db_session.flush()
    return order


@pytest.fixture
async def upsell_fixture(db_session, restaurant):
    from app.menu.models import Dish, Menu
    from app.ordering.models import Customer

    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()

    dish_a = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1, name="Dish A",
        price_aed=Decimal("10.00"), is_available=True, name_normalized="dish a",
    )
    dish_b = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=2, name="Dish B",
        price_aed=Decimal("10.00"), is_available=True, name_normalized="dish b",
    )
    dish_c = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=3, name="Dish C",
        price_aed=Decimal("10.00"), is_available=True, name_normalized="dish c",
    )
    dish_unavailable = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=4, name="Dish D (unavail)",
        price_aed=Decimal("10.00"), is_available=False, name_normalized="dish d",
    )
    db_session.add_all([dish_a, dish_b, dish_c, dish_unavailable])
    await db_session.flush()

    cust = Customer(restaurant_id=restaurant.id, phone="+971500000099", name="Upsell Test")
    db_session.add(cust)
    await db_session.flush()

    # A+B co-occur 3 times (delivered/confirmed orders)
    await _make_order(db_session, restaurant, cust, "UP-0001", "delivered", [(dish_a, 1), (dish_b, 1)])
    await _make_order(db_session, restaurant, cust, "UP-0002", "delivered", [(dish_a, 1), (dish_b, 1)])
    await _make_order(db_session, restaurant, cust, "UP-0003", "confirmed", [(dish_a, 1), (dish_b, 1)])
    # A+C co-occur once
    await _make_order(db_session, restaurant, cust, "UP-0004", "delivered", [(dish_a, 1), (dish_c, 1)])
    # A+D (unavailable dish) co-occurs but D must be excluded from results
    await _make_order(db_session, restaurant, cust, "UP-0005", "delivered", [(dish_a, 1), (dish_unavailable, 1)])
    # Cancelled/draft orders must not count
    await _make_order(db_session, restaurant, cust, "UP-0006", "cancelled", [(dish_a, 1), (dish_c, 1)])
    await _make_order(db_session, restaurant, cust, "UP-0007", "draft", [(dish_a, 1), (dish_c, 1)])
    await db_session.commit()

    return {
        "menu": menu, "dish_a": dish_a, "dish_b": dish_b, "dish_c": dish_c,
        "dish_unavailable": dish_unavailable, "customer": cust,
    }


@pytest.mark.anyio
async def test_ranks_more_frequent_co_purchase_higher(db_session, restaurant, upsell_fixture):
    dish_a = upsell_fixture["dish_a"]
    dish_b = upsell_fixture["dish_b"]
    dish_c = upsell_fixture["dish_c"]

    results = await compute_co_purchase_scores(
        db_session, restaurant_id=restaurant.id, dish_ids=[dish_a.id],
    )

    assert len(results) >= 2
    assert results[0]["dish_id"] == dish_b.id
    assert results[0]["dish_name"] == "Dish B"
    assert results[0]["co_occurrence_count"] == 3
    b_index = next(i for i, r in enumerate(results) if r["dish_id"] == dish_b.id)
    c_index = next(i for i, r in enumerate(results) if r["dish_id"] == dish_c.id)
    assert b_index < c_index


@pytest.mark.anyio
async def test_excludes_dishes_already_in_cart(db_session, restaurant, upsell_fixture):
    dish_a = upsell_fixture["dish_a"]
    dish_b = upsell_fixture["dish_b"]

    results = await compute_co_purchase_scores(
        db_session, restaurant_id=restaurant.id, dish_ids=[dish_a.id, dish_b.id],
    )
    result_ids = {r["dish_id"] for r in results}
    assert dish_a.id not in result_ids
    assert dish_b.id not in result_ids


@pytest.mark.anyio
async def test_excludes_unavailable_dishes(db_session, restaurant, upsell_fixture):
    dish_a = upsell_fixture["dish_a"]
    dish_unavailable = upsell_fixture["dish_unavailable"]

    results = await compute_co_purchase_scores(
        db_session, restaurant_id=restaurant.id, dish_ids=[dish_a.id],
    )
    result_ids = {r["dish_id"] for r in results}
    assert dish_unavailable.id not in result_ids


@pytest.mark.anyio
async def test_respects_limit(db_session, restaurant, upsell_fixture):
    dish_a = upsell_fixture["dish_a"]

    results = await compute_co_purchase_scores(
        db_session, restaurant_id=restaurant.id, dish_ids=[dish_a.id], limit=1,
    )
    assert len(results) == 1


@pytest.mark.anyio
async def test_cold_start_returns_empty_list(db_session, restaurant):
    """No order history at all for this restaurant -> empty list, no fabricated fallback."""
    results = await compute_co_purchase_scores(
        db_session, restaurant_id=restaurant.id, dish_ids=[999999],
    )
    assert results == []


@pytest.mark.anyio
async def test_upsell_router_returns_ranked_suggestions(client, db_session, restaurant, upsell_fixture):
    dish_a = upsell_fixture["dish_a"]
    dish_b = upsell_fixture["dish_b"]
    headers = {"Authorization": f"Bearer {_token_for(restaurant.id)}"}

    resp = await client.get(
        f"/api/v1/menu/upsell?dish_ids={dish_a.id}&limit=3", headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body, list)
    assert body[0]["dish_id"] == dish_b.id
    assert body[0]["co_occurrence_count"] == 3


@pytest.mark.anyio
async def test_upsell_router_cold_start_empty(client, db_session, restaurant):
    headers = {"Authorization": f"Bearer {_token_for(restaurant.id)}"}
    resp = await client.get(
        "/api/v1/menu/upsell?dish_ids=999999&limit=3", headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []
