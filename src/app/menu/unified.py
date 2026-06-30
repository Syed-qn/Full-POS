"""Unified menu view: text dishes + Meta catalogue products with link status."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import CatalogProduct
from app.catalog.sync_service import list_catalog_products
from app.menu.models import Dish, Menu


class UnifiedMenuItemOut(BaseModel):
    """One row in the manager's single menu — dish, catalogue product, or both."""

    link_status: str  # linked | dish_only | catalog_only
    dish_id: int | None = None
    catalog_product_id: int | None = None
    retailer_id: str | None = None
    dish_number: int | None = None
    name: str
    price_aed: Decimal | None = None
    category: str | None = None
    description: str | None = None
    is_available: bool = True
    catalog_active: bool | None = None
    image_url: str | None = None
    # Whether this linked product is actually live on WhatsApp (Meta finished processing
    # its image) vs still "in review". Drives the dashboard pill. None when not on the
    # catalogue at all.
    sendable: bool | None = None
    review_status: str | None = None


class UnifiedMenuOut(BaseModel):
    menu_id: int | None
    catalog_id: str
    items: list[UnifiedMenuItemOut]
    linked_count: int
    dish_only_count: int
    catalog_only_count: int


async def build_unified_menu(
    session: AsyncSession, *, restaurant_id: int, catalog_id: str = ""
) -> UnifiedMenuOut:
    """Merge active-menu dishes and synced catalogue products by retailer_id / name."""
    menu = await session.scalar(
        select(Menu)
        .where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
        .order_by(Menu.version.desc())
        .limit(1)
    )
    dishes: list[Dish] = []
    if menu is not None:
        dishes = list(
            (
                await session.scalars(
                    select(Dish)
                    .where(Dish.menu_id == menu.id, Dish.meta_status != "archived")
                    .order_by(Dish.category, Dish.dish_number)
                )
            ).all()
        )

    catalog_rows = await list_catalog_products(session, restaurant_id=restaurant_id)
    catalog_by_rid: dict[str, CatalogProduct] = {
        p.retailer_id: p for p in catalog_rows if p.retailer_id
    }
    catalog_by_name: dict[str, CatalogProduct] = {
        (p.name or "").casefold(): p for p in catalog_rows
    }

    items: list[UnifiedMenuItemOut] = []
    seen_rids: set[str] = set()
    linked = dish_only = catalog_only = 0

    for dish in dishes:
        rid = (dish.catalog_retailer_id or "").strip() or None
        cat = catalog_by_rid.get(rid) if rid else None
        if cat is None and dish.name_normalized:
            cat = catalog_by_name.get(dish.name_normalized)
        if rid:
            seen_rids.add(rid)
        elif cat is not None:
            seen_rids.add(cat.retailer_id)
            rid = cat.retailer_id

        if cat is not None and rid:
            status = "linked"
            linked += 1
            # Dish price is source of truth — we push it to Meta on sync.
            price = dish.price_aed if dish.price_aed is not None else cat.price_aed
        else:
            status = "dish_only"
            dish_only += 1
            price = dish.price_aed

        items.append(
            UnifiedMenuItemOut(
                link_status=status,
                dish_id=dish.id,
                catalog_product_id=cat.id if cat else None,
                retailer_id=rid,
                dish_number=dish.dish_number,
                name=dish.name,
                price_aed=price,
                category=dish.category or (cat.category if cat else None),
                description=dish.description,
                is_available=dish.is_available,
                catalog_active=cat.is_active if cat else None,
                image_url=cat.image_url if cat else None,
                sendable=cat.is_sendable if cat else None,
                review_status=cat.review_status if cat else None,
            )
        )

    for p in catalog_rows:
        if not p.retailer_id or p.retailer_id in seen_rids:
            continue
        catalog_only += 1
        items.append(
            UnifiedMenuItemOut(
                link_status="catalog_only",
                catalog_product_id=p.id,
                retailer_id=p.retailer_id,
                name=p.name,
                price_aed=p.price_aed,
                category=p.category,
                is_available=False,
                catalog_active=p.is_active,
                image_url=p.image_url,
                sendable=p.is_sendable,
                review_status=p.review_status,
            )
        )

    return UnifiedMenuOut(
        menu_id=menu.id if menu else None,
        catalog_id=catalog_id,
        items=items,
        linked_count=linked,
        dish_only_count=dish_only,
        catalog_only_count=catalog_only,
    )