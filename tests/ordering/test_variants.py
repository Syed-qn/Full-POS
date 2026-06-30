from decimal import Decimal

from app.menu.models import Dish, Menu
from app.ordering.matching import bundle_variant_for_qty, resolve_variant
from app.ordering.service import add_item, create_draft_order, get_or_create_customer


async def _seed(db_session, restaurant):
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    biryani = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=1,
        name="Chicken Biryani", price_aed=Decimal("18.00"),
        category="Biryani", is_available=True, name_normalized="chicken biryani",
        variants=[
            {"name": "1 serve", "price_aed": "18.00", "dish_number": None},
            {"name": "4 serve", "price_aed": "60.00", "dish_number": None},
        ],
    )
    lassi = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=7,
        name="Mango Lassi", price_aed=Decimal("12.00"),
        category="Drinks", is_available=True, name_normalized="mango lassi",
    )
    db_session.add_all([biryani, lassi])
    await db_session.flush()
    customer = await get_or_create_customer(
        db_session, restaurant_id=restaurant.id, phone="+971500000123",
    )
    order = await create_draft_order(
        db_session, restaurant_id=restaurant.id, customer_id=customer.id
    )
    await db_session.flush()
    return order, biryani, lassi


def test_resolve_variant_fuzzy():
    dish = Dish(
        name="Chicken Biryani",
        variants=[
            {"name": "1 serve", "price_aed": "18.00", "dish_number": None},
            {"name": "4 serve", "price_aed": "60.00", "dish_number": None},
        ],
    )
    assert resolve_variant(dish, "4 serve")["price_aed"] == "60.00"
    assert resolve_variant(dish, "4")["name"] == "4 serve"
    assert resolve_variant(dish, "i want the 4 serve please")["name"] == "4 serve"
    assert resolve_variant(dish, "family") is None  # not a defined variant


def test_resolve_variant_no_variants_returns_none():
    assert resolve_variant(Dish(name="Mango Lassi", variants=[]), "large") is None


def test_bundle_variant_for_qty():
    dish = Dish(
        name="Chicken Biryani",
        variants=[
            {"name": "2 serve", "price_aed": "30.00", "dish_number": None},
            {"name": "4 serve", "price_aed": "55.00", "dish_number": None},
        ],
    )
    assert bundle_variant_for_qty(dish, 2)["name"] == "2 serve"
    assert bundle_variant_for_qty(dish, 4)["name"] == "4 serve"
    assert bundle_variant_for_qty(dish, 3) is None  # no 3-serve bundle
    assert bundle_variant_for_qty(dish, 1) is None  # single is the base price


async def test_add_item_without_variant_unchanged(db_session, restaurant):
    order, _biryani, lassi = await _seed(db_session, restaurant)
    item = await add_item(db_session, order=order, dish=lassi, qty=2)
    assert item.variant_name is None
    assert item.price_aed == Decimal("12.00")
    assert order.total == Decimal("24.00")


async def test_add_item_uses_sale_price_when_set(db_session, restaurant):
    """A dish on sale is added to the cart at its sale price, not the base price."""
    order, _biryani, lassi = await _seed(db_session, restaurant)
    lassi.sale_price_aed = Decimal("8.00")  # base 12 → sale 8
    await db_session.flush()
    item = await add_item(db_session, order=order, dish=lassi, qty=2)
    assert item.price_aed == Decimal("8.00")
    assert order.total == Decimal("16.00")


async def test_add_item_ignores_invalid_sale_price(db_session, restaurant):
    """A sale price that isn't below the base price is ignored (charges base)."""
    order, _biryani, lassi = await _seed(db_session, restaurant)
    lassi.sale_price_aed = Decimal("20.00")  # >= base 12 → ignore
    await db_session.flush()
    item = await add_item(db_session, order=order, dish=lassi, qty=1)
    assert item.price_aed == Decimal("12.00")


async def test_add_item_with_variant_snapshots_price(db_session, restaurant):
    order, biryani, _lassi = await _seed(db_session, restaurant)
    variant = {"name": "4 serve", "price_aed": "60.00", "dish_number": None}
    item = await add_item(db_session, order=order, dish=biryani, qty=2, variant=variant)
    assert item.variant_name == "4 serve"
    assert item.price_aed == Decimal("60.00")
    assert order.total == Decimal("120.00")


async def test_different_variants_are_separate_lines(db_session, restaurant):
    from sqlalchemy import select

    from app.ordering.models import OrderItem

    order, biryani, _lassi = await _seed(db_session, restaurant)
    await add_item(db_session, order=order, dish=biryani, qty=1,
                   variant={"name": "1 serve", "price_aed": "18.00"})
    await add_item(db_session, order=order, dish=biryani, qty=1,
                   variant={"name": "4 serve", "price_aed": "60.00"})
    # Same variant again merges into the first line.
    await add_item(db_session, order=order, dish=biryani, qty=1,
                   variant={"name": "1 serve", "price_aed": "18.00"})

    lines = (
        await db_session.scalars(
            select(OrderItem).where(OrderItem.order_id == order.id)
        )
    ).all()
    by_variant = {line.variant_name: line.qty for line in lines}
    assert by_variant == {"1 serve": 2, "4 serve": 1}
    assert order.total == Decimal("96.00")  # 2*18 + 1*60
