"""Shared Meta catalogue: one filter module, every menu surface."""
from decimal import Decimal

from sqlalchemy import select

from app.catalog.models import CatalogProduct
from app.catalog.sync_service import list_catalog_products
from app.catalog.tenant_scope import is_shared_catalog, native_catalog_view_allowed
from app.menu.models import Dish, Menu


async def _seed_lims_shared(db_session, restaurant):
    from app.identity.models import Restaurant

    lims = Restaurant(
        name="Lims", phone="+919344471586", password_hash="x", lat=25.0, lng=55.0,
        settings={"catalog_id": "SHARED", "catalog_ordering_enabled": True},
    )
    db_session.add(lims)
    await db_session.flush()
    b_menu = Menu(restaurant_id=restaurant.id, version=1, status="active", source_files=[])
    l_menu = Menu(restaurant_id=lims.id, version=1, status="active", source_files=[])
    db_session.add_all([b_menu, l_menu])
    await db_session.flush()
    b_dish = Dish(
        menu_id=b_menu.id, restaurant_id=restaurant.id, dish_number=1, name="Biryani Plate",
        price_aed=Decimal("50"), category="Rice", is_available=True,
        name_normalized="biryani plate", catalog_retailer_id="dish-b-1",
    )
    l_dish = Dish(
        menu_id=l_menu.id, restaurant_id=lims.id, dish_number=1, name="Lims Special",
        price_aed=Decimal("40"), category="Rice", is_available=True,
        name_normalized="lims special", catalog_retailer_id="dish-l-1",
    )
    db_session.add_all([b_dish, l_dish])
    await db_session.flush()
    db_session.add_all([
        CatalogProduct(
            restaurant_id=lims.id, retailer_id="dish-b-1", name="Biryani Plate",
            price_aed=Decimal("50"), currency="AED", availability="in stock",
            category="Rice", is_active=True, is_sendable=True, raw={},
        ),
        CatalogProduct(
            restaurant_id=lims.id, retailer_id="dish-l-1", name="Lims Special",
            price_aed=Decimal("40"), currency="AED", availability="in stock",
            category="Rice", is_active=True, is_sendable=True, raw={},
        ),
    ])
    restaurant.settings = {**restaurant.settings, "catalog_id": "SHARED",
                           "catalog_ordering_enabled": True}
    await db_session.commit()
    return lims


async def test_list_catalog_products_is_tenant_scoped(db_session, restaurant):
    lims = await _seed_lims_shared(db_session, restaurant)
    rows = await list_catalog_products(db_session, restaurant_id=lims.id)
    assert len(rows) == 1
    assert rows[0].retailer_id == "dish-l-1"


async def test_native_catalog_view_follows_per_tenant_flag(db_session, restaurant):
    from app.menu.models import Dish, Menu

    lims = await _seed_lims_shared(db_session, restaurant)
    assert await is_shared_catalog(db_session, restaurant_id=lims.id) is True
    # Primary on shared Feasto (more dishes) → native view allowed.
    b_menu = await db_session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant.id, Menu.status == "active")
    )
    for i in range(5):
        db_session.add(
            Dish(
                menu_id=b_menu.id,
                restaurant_id=restaurant.id,
                dish_number=10 + i,
                name=f"Extra {i}",
                price_aed=Decimal("10"),
                category="Rice",
                is_available=True,
                whatsapp_enabled=True,
                meta_status="active",
                name_normalized=f"extra {i}",
                catalog_retailer_id=f"dish-b-extra-{i}",
            )
        )
    await db_session.commit()
    assert await native_catalog_view_allowed(
        db_session, restaurant_id=restaurant.id, settings={"catalog_id": "SHARED"},
    ) is True
    # Secondary on shared Feasto → native view blocked (even if flag true).
    assert await native_catalog_view_allowed(
        db_session,
        restaurant_id=lims.id,
        settings={"catalog_native_view": True, "catalog_id": "SHARED"},
    ) is False
    # Dedicated catalogue (no sibling) → default native view ON.
    lims.settings = {"catalog_id": "LIMS-OWN", "catalog_ordering_enabled": True}
    await db_session.commit()
    assert await is_shared_catalog(db_session, restaurant_id=lims.id) is False
    assert await native_catalog_view_allowed(
        db_session, restaurant_id=lims.id, settings=lims.settings,
    ) is True