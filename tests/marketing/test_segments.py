from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.llm.factory import get_segment_compiler
from app.llm.fake import FakeSegmentCompiler
from app.marketing.segments import (
    evaluate_segment,
    preview_count,
    validate_dsl,
)
from app.ordering.models import Customer, Order, OrderItem


async def _seed_customers(db_session, restaurant_id: int) -> dict[str, int]:
    """Seed 3 customers with varying spend/tags + a couple of orders.

    Returns a name->customer_id map (dynamic ids, never hardcoded).
    """
    now = datetime.now(timezone.utc)

    big = Customer(
        restaurant_id=restaurant_id, phone="+971500000001", name="Big Spender",
        usual_order_times={}, tags={"vip": True}, total_orders=5,
        total_spend=Decimal("350.00"),
        first_order_at=now - timedelta(days=90), last_order_at=now - timedelta(days=2),
    )
    small = Customer(
        restaurant_id=restaurant_id, phone="+971500000002", name="Small Spender",
        usual_order_times={}, tags={}, total_orders=1,
        total_spend=Decimal("40.00"),
        first_order_at=now - timedelta(days=10), last_order_at=now - timedelta(days=200),
    )
    mid = Customer(
        restaurant_id=restaurant_id, phone="+971500000003", name="Mid Spender",
        usual_order_times={}, tags={"regular": True}, total_orders=3,
        total_spend=Decimal("210.00"),
        first_order_at=now - timedelta(days=40), last_order_at=now - timedelta(days=5),
    )
    db_session.add_all([big, small, mid])
    await db_session.flush()

    from app.menu.models import Dish, Menu

    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    dish = Dish(
        menu_id=menu.id, restaurant_id=restaurant_id, dish_number=110,
        name="Chicken Biryani", price_aed=Decimal("22.00"), category="Rice",
        is_available=True, name_normalized="chicken biryani",
    )
    db_session.add(dish)
    await db_session.flush()

    # Big ordered the dish three times across two orders; mid ordered it once.
    o1 = Order(
        restaurant_id=restaurant_id, customer_id=big.id, order_number="R1-S1",
        status="delivered", subtotal=Decimal("66.00"), total=Decimal("66.00"),
    )
    o2 = Order(
        restaurant_id=restaurant_id, customer_id=mid.id, order_number="R1-S2",
        status="delivered", subtotal=Decimal("22.00"), total=Decimal("22.00"),
    )
    db_session.add_all([o1, o2])
    await db_session.flush()
    db_session.add_all([
        OrderItem(order_id=o1.id, dish_id=dish.id, dish_number=110,
                  dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=3),
        OrderItem(order_id=o2.id, dish_id=dish.id, dish_number=110,
                  dish_name="Chicken Biryani", price_aed=Decimal("22.00"), qty=1),
    ])
    await db_session.commit()
    return {"big": big.id, "small": small.id, "mid": mid.id, "dish": dish.id}


async def test_evaluate_total_spend_gte(db_session, restaurant):
    ids = await _seed_customers(db_session, restaurant.id)
    dsl = {"all": [{"field": "total_spend", "op": "gte", "value": 200}]}
    result = await evaluate_segment(db_session, restaurant_id=restaurant.id, dsl=dsl)
    assert set(result) == {ids["big"], ids["mid"]}


async def test_evaluate_tag_contains(db_session, restaurant):
    ids = await _seed_customers(db_session, restaurant.id)
    dsl = {"all": [{"field": "tag", "op": "contains", "value": "vip"}]}
    result = await evaluate_segment(db_session, restaurant_id=restaurant.id, dsl=dsl)
    assert set(result) == {ids["big"]}


async def test_evaluate_any_or(db_session, restaurant):
    ids = await _seed_customers(db_session, restaurant.id)
    dsl = {"any": [
        {"field": "tag", "op": "contains", "value": "vip"},
        {"field": "order_count", "op": "gte", "value": 3},
    ]}
    result = await evaluate_segment(db_session, restaurant_id=restaurant.id, dsl=dsl)
    assert set(result) == {ids["big"], ids["mid"]}


async def test_evaluate_last_order_days_ago(db_session, restaurant):
    ids = await _seed_customers(db_session, restaurant.id)
    dsl = {"all": [{"field": "last_order_days_ago", "op": "lte", "value": 30}]}
    result = await evaluate_segment(db_session, restaurant_id=restaurant.id, dsl=dsl)
    assert set(result) == {ids["big"], ids["mid"]}


async def test_evaluate_ordered_dish_min_count(db_session, restaurant):
    ids = await _seed_customers(db_session, restaurant.id)
    dsl = {"all": [
        {"field": "ordered_dish_id", "op": "eq", "value": ids["dish"], "min_count": 3},
    ]}
    result = await evaluate_segment(db_session, restaurant_id=restaurant.id, dsl=dsl)
    assert set(result) == {ids["big"]}


async def test_evaluate_is_tenant_scoped(db_session, restaurant):
    """A customer in another restaurant must never appear in results."""
    from app.identity.models import Restaurant

    other = Restaurant(name="Other", phone="+97140000000", password_hash="x",
                       lat=25.0, lng=55.0)
    db_session.add(other)
    await db_session.flush()
    db_session.add(Customer(
        restaurant_id=other.id, phone="+971599999999", name="Outsider",
        usual_order_times={}, tags={"vip": True}, total_orders=9,
        total_spend=Decimal("999.00"),
    ))
    await db_session.commit()
    ids = await _seed_customers(db_session, restaurant.id)

    dsl = {"all": [{"field": "total_spend", "op": "gte", "value": 200}]}
    result = await evaluate_segment(db_session, restaurant_id=restaurant.id, dsl=dsl)
    assert set(result) == {ids["big"], ids["mid"]}


async def test_preview_count(db_session, restaurant):
    await _seed_customers(db_session, restaurant.id)
    dsl = {"all": [{"field": "total_spend", "op": "gte", "value": 200}]}
    n = await preview_count(db_session, restaurant_id=restaurant.id, dsl=dsl)
    assert n == 2


@pytest.mark.parametrize("bad", [
    {"all": [{"field": "DROP", "op": "eq", "value": 1}]},
    {"all": [{"field": "total_spend", "op": "regexp", "value": 1}]},
    {"all": [{"field": "total_spend", "value": 1}]},  # missing op
    {"any": "not-a-list"},
    {"unknown_root": []},
    {"all": [{"field": "tag", "op": "gte", "value": "vip"}]},  # op not allowed for tag
    "not-a-dict",
])
def test_validate_dsl_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        validate_dsl(bad)


def test_validate_dsl_accepts_valid():
    validate_dsl({"all": [
        {"field": "total_spend", "op": "gte", "value": 200},
        {"field": "tag", "op": "contains", "value": "vip"},
        {"field": "order_count", "op": "gte", "value": 3},
        {"field": "last_order_days_ago", "op": "lte", "value": 30},
        {"field": "ordered_dish_id", "op": "eq", "value": 1, "min_count": 3},
    ]})


def test_fake_compiler_spend():
    dsl = FakeSegmentCompiler().compile("customers who spent over 200 aed")
    validate_dsl(dsl)
    cond = dsl["all"][0]
    assert cond["field"] == "total_spend"
    assert cond["op"] == "gte"
    assert cond["value"] == 200


def test_fake_compiler_vip():
    dsl = FakeSegmentCompiler().compile("our vip customers")
    validate_dsl(dsl)
    assert {"field": "tag", "op": "contains", "value": "vip"} in dsl["all"]


def test_fake_compiler_recency():
    dsl = FakeSegmentCompiler().compile("people who ordered in the last 30 days")
    validate_dsl(dsl)
    assert {"field": "last_order_days_ago", "op": "lte", "value": 30} in dsl["all"]


def test_factory_returns_fake_by_default():
    compiler = get_segment_compiler()
    assert isinstance(compiler, FakeSegmentCompiler)
    validate_dsl(compiler.compile("customers who spent over 200 aed"))
