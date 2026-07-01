"""POS → dishes sync (Cratis), driven by the FakePos provider (no network)."""
from decimal import Decimal

from sqlalchemy import select

from app.menu.models import Dish
from app.pos.cratis import parse_cratis_menu
from app.pos.images import generate_dish_image
from app.pos.mapper import map_pos_menu
from app.pos.port import FakePos, PosCategory, PosMenu, PosProduct
from app.pos.sync_service import sync_menu_from_pos


def _menu(products) -> PosMenu:
    return PosMenu(
        categories=[
            PosCategory(pos_category_id="220", name="APPETIZER"),
            PosCategory(pos_category_id="227", name="COLD BEVERAGES"),
        ],
        products=products,
    )


def _prod(pid, name, price, cat="220", ptype=1):
    return PosProduct(
        pos_product_id=pid, name=name, price=Decimal(str(price)),
        category_id=cat, product_type=ptype,
    )


async def _configure(db_session, restaurant):
    restaurant.settings = {**(restaurant.settings or {}),
                           "pos_account": "hnc", "pos_location": "HNC002"}
    await db_session.commit()


# ── pure units ────────────────────────────────────────────────────────────────

def test_mapper_keeps_only_sellable_items():
    menu = _menu([
        _prod("1", "-SAMOSA CHEESE", 12, ptype=1),
        _prod("2", "Extra Cheese", 2, ptype=2),   # modifier → dropped
        _prod("3", "Combo", 30, ptype=3),         # combo → dropped
    ])
    recs = map_pos_menu(menu)
    assert [r.pos_product_id for r in recs] == ["1"]
    assert recs[0].name == "Samosa Cheese"  # leading "-" dropped, ALL-CAPS title-cased
    assert recs[0].category == "APPETIZER"
    assert recs[0].price_aed == Decimal("12")


def test_parse_cratis_menu_normalizes():
    data = {
        "categories": [{"name": "APPETIZER", "posCategoryId": "220", "imageUrl": ""}],
        "products": [{
            "posProductId": "19680", "name": "Samosa", "price": 12.0,
            "posCategoryIds": "220", "productType": 1, "plu": "EXAP001",
            "nameTranslations": {"ar": "سمبوسة"}, "description": "Crispy",
        }],
    }
    menu = parse_cratis_menu(data)
    assert len(menu.products) == 1
    p = menu.products[0]
    assert p.pos_product_id == "19680" and p.price == Decimal("12.0")
    assert menu.category_name(p.category_id) == "APPETIZER"


def test_generate_dish_image_returns_png():
    png = generate_dish_image("Chicken Biryani")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"  # PNG signature
    assert len(png) > 200


# ── sync behaviour ──────────────────────────────────────────────────────────────

async def test_sync_creates_dishes_and_images(db_session, restaurant):
    await _configure(db_session, restaurant)
    provider = FakePos(_menu([
        _prod("19680", "Samosa Cheese", 12),
        _prod("19697", "Apple Juice", 9, cat="227"),
        _prod("50001", "Extra Cheese", 2, ptype=2),  # modifier → ignored
    ]))
    res = await sync_menu_from_pos(db_session, restaurant_id=restaurant.id, provider=provider)
    await db_session.commit()
    assert (res.fetched, res.created, res.updated, res.deactivated) == (2, 2, 0, 0)
    assert res.images == 2
    dishes = {d.pos_product_id: d for d in (await db_session.scalars(
        select(Dish).where(Dish.restaurant_id == restaurant.id, Dish.pos_product_id.is_not(None))
    )).all()}
    assert set(dishes) == {"19680", "19697"}
    assert dishes["19680"].category == "APPETIZER"
    assert dishes["19697"].price_aed == Decimal("9.00")
    assert "/media/dishes/" in (dishes["19680"].image_url or "")
    assert dishes["19680"].dish_number is not None


async def test_sync_is_idempotent_and_preserves_local_fields(db_session, restaurant):
    await _configure(db_session, restaurant)
    provider = FakePos(_menu([_prod("19680", "Samosa", 12)]))
    await sync_menu_from_pos(db_session, restaurant_id=restaurant.id, provider=provider)
    await db_session.commit()

    dish = await db_session.scalar(
        select(Dish).where(Dish.pos_product_id == "19680")
    )
    # Manager-set local fields that POS must never overwrite.
    dish.sale_price_aed = Decimal("8.00")
    dish.whatsapp_enabled = False
    dish.image_url = "https://example.com/media/dishes/1/custom.png"
    await db_session.commit()
    dish_id = dish.id

    # Re-sync with a NEW price for the same POS id → update in place, keep local fields.
    provider2 = FakePos(_menu([_prod("19680", "Samosa Special", 15)]))
    res = await sync_menu_from_pos(db_session, restaurant_id=restaurant.id, provider=provider2)
    await db_session.commit()
    assert (res.created, res.updated) == (0, 1)
    dish2 = await db_session.get(Dish, dish_id)
    assert dish2.name == "Samosa Special"          # POS-owned, updated
    assert dish2.price_aed == Decimal("15.00")     # POS-owned, updated
    assert dish2.sale_price_aed == Decimal("8.00")  # local, preserved
    assert dish2.whatsapp_enabled is False          # local, preserved
    assert dish2.image_url.endswith("custom.png")   # local, preserved


async def test_sync_removes_item_gone_from_pos(db_session, restaurant):
    await _configure(db_session, restaurant)
    await sync_menu_from_pos(
        db_session, restaurant_id=restaurant.id,
        provider=FakePos(_menu([_prod("a", "Keep", 10), _prod("b", "Gone", 20)])),
    )
    await db_session.commit()
    # Second sync without "b" → b is removed (no orders → hard delete).
    res = await sync_menu_from_pos(
        db_session, restaurant_id=restaurant.id,
        provider=FakePos(_menu([_prod("a", "Keep", 10)])),
    )
    await db_session.commit()
    assert res.deactivated == 1
    assert await db_session.scalar(select(Dish).where(Dish.pos_product_id == "b")) is None
    assert await db_session.scalar(select(Dish).where(Dish.pos_product_id == "a")) is not None


async def test_sync_aborts_on_empty_pos(db_session, restaurant):
    await _configure(db_session, restaurant)
    await sync_menu_from_pos(
        db_session, restaurant_id=restaurant.id,
        provider=FakePos(_menu([_prod("a", "Keep", 10)])),
    )
    await db_session.commit()
    # POS returns nothing → abort, do NOT wipe the existing POS dish.
    res = await sync_menu_from_pos(
        db_session, restaurant_id=restaurant.id, provider=FakePos(_menu([])),
    )
    await db_session.commit()
    assert res.skipped_empty is True
    assert await db_session.scalar(select(Dish).where(Dish.pos_product_id == "a")) is not None


async def test_sync_leaves_manual_dishes_untouched(db_session, restaurant):
    """A manually-created dish (no pos_product_id) is never removed by POS sync."""
    from app.menu.models import Menu

    await _configure(db_session, restaurant)
    menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    db_session.add(menu)
    await db_session.flush()
    manual = Dish(
        menu_id=menu.id, restaurant_id=restaurant.id, dish_number=999, name="Manual Dish",
        price_aed=Decimal("25.00"), is_available=True, name_normalized="manual dish",
    )
    db_session.add(manual)
    await db_session.commit()
    manual_id = manual.id

    await sync_menu_from_pos(
        db_session, restaurant_id=restaurant.id,
        provider=FakePos(_menu([_prod("a", "Pos Dish", 10)])),
    )
    await db_session.commit()
    assert await db_session.get(Dish, manual_id) is not None  # untouched
