"""Sync a restaurant's Meta Commerce catalogue into local ``catalog_products``.

Driven by the OPS "Sync from Meta" button (catalog mode only). Reads the catalogue
from Meta (``meta_client.fetch_catalog_products``) and upserts one row per
(restaurant, retailer_id), marking products that vanished from Meta as inactive.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.meta_client import (
    CatalogReadError,
    CatalogWriteError,
    _dish_retailer_id,
    build_catalog_item_data,
    fetch_catalog_products,
    push_products_batch,
)
from app.catalog.models import CatalogProduct
from app.config import get_settings
from app.identity.models import Restaurant

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    added: int = 0
    updated: int = 0
    deactivated: int = 0
    total_active: int = 0
    linked: int = 0    # existing dishes linked to a catalogue product by name
    created: int = 0   # orderable dishes auto-created for catalogue products w/o a dish
    pushed: int = 0    # dishes pushed to Meta on outbound sync
    push_updated: int = 0
    push_errors: list[str] = field(default_factory=list)


async def _ensure_orderable_dishes(session: AsyncSession, *, restaurant_id: int, products) -> tuple[int, int]:
    """Every catalogue product must map to an orderable Dish (the cart adds Dishes, and
    the conversation engine treats a typed item as 'in the catalogue' only when its Dish
    is linked via ``catalog_retailer_id``). For each synced product: if a dish is already
    linked → leave it; else link a same-named unlinked dish; else AUTO-CREATE a dish from
    the product. So adding a product in Meta + syncing makes it orderable (typed AND
    tapped) with no manual wiring. Returns (linked, created)."""
    from app.menu.models import Dish, Menu
    from app.ordering.matching import normalize_name

    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    ) or await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id).order_by(Menu.version.desc())
    )
    linked = created = 0
    for p in products:
        rid = (p.retailer_id or "").strip()
        if not rid:
            continue
        already = await session.scalar(
            select(Dish.id).where(
                Dish.restaurant_id == restaurant_id, Dish.catalog_retailer_id == rid
            ).limit(1)
        )
        if already:
            continue
        norm = normalize_name(p.name)
        dish = await session.scalar(
            select(Dish).where(
                Dish.restaurant_id == restaurant_id,
                Dish.name_normalized == norm,
                Dish.catalog_retailer_id.is_(None),
            ).limit(1)
        )
        if dish is not None:
            dish.catalog_retailer_id = rid
            linked += 1
            continue
        # No matching dish → create a lightweight orderable one from the product.
        if menu is None:
            menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
            session.add(menu)
            await session.flush()
        session.add(Dish(
            menu_id=menu.id, restaurant_id=restaurant_id, name=p.name,
            price_aed=p.price_aed, category=p.category, is_available=True,
            name_normalized=norm, catalog_retailer_id=rid,
        ))
        created += 1
    return linked, created


async def _mirror_dishes_to_catalog(
    session: AsyncSession,
    *,
    restaurant_id: int,
    dishes: list,
) -> tuple[int, int]:
    """Upsert local ``catalog_products`` from pushed dishes (don't wait for Meta re-pull)."""
    now = datetime.now(timezone.utc)
    added = updated = 0
    for dish in dishes:
        rid = (dish.catalog_retailer_id or "").strip()
        if not rid or dish.price_aed is None:
            continue
        row = await session.scalar(
            select(CatalogProduct).where(
                CatalogProduct.restaurant_id == restaurant_id,
                CatalogProduct.retailer_id == rid,
            ).limit(1)
        )
        if row is None:
            row = CatalogProduct(restaurant_id=restaurant_id, retailer_id=rid)
            session.add(row)
            added += 1
        else:
            updated += 1
        row.name = dish.name
        row.price_aed = dish.price_aed
        row.currency = "AED"
        row.availability = "in stock" if dish.is_available else "out of stock"
        row.category = dish.category
        row.is_active = dish.is_available
        row.synced_at = now
        row.raw = {
            "retailer_id": rid,
            "name": dish.name,
            "price": f"{dish.price_aed:.2f} AED",
            "source": "local_push",
        }
    return added, updated


async def sync_catalog_from_meta(session: AsyncSession, *, restaurant_id: int) -> SyncResult:
    """Pull the restaurant's Meta catalogue and upsert ``catalog_products``.

    Raises ``CatalogReadError`` (token/permission/id problems) or ValueError (no
    catalog_id) so the router can return a clear message. Caller commits.
    """
    rest = await session.get(Restaurant, restaurant_id)
    settings = (rest.settings or {}) if rest is not None else {}
    catalog_id = (settings.get("catalog_id") or "").strip()
    if not catalog_id:
        raise CatalogReadError("Set a Catalog ID in Settings before syncing.")

    products = await fetch_catalog_products(catalog_id)
    now = datetime.now(timezone.utc)

    existing = {
        row.retailer_id: row
        for row in (
            await session.scalars(
                select(CatalogProduct).where(CatalogProduct.restaurant_id == restaurant_id)
            )
        ).all()
    }
    seen: set[str] = set()
    result = SyncResult()

    for p in products:
        seen.add(p.retailer_id)
        row = existing.get(p.retailer_id)
        if row is None:
            row = CatalogProduct(restaurant_id=restaurant_id, retailer_id=p.retailer_id)
            session.add(row)
            result.added += 1
        else:
            result.updated += 1
        row.meta_product_id = p.meta_product_id
        row.name = p.name
        row.price_aed = p.price_aed
        row.currency = p.currency
        row.availability = p.availability
        row.image_url = p.image_url
        row.category = p.category
        row.raw = p.raw
        row.is_active = True
        row.synced_at = now

    # Products that disappeared from Meta → mark inactive (don't delete, keep history
    # + any order references intact).
    for retailer_id, row in existing.items():
        if retailer_id not in seen and row.is_active:
            row.is_active = False
            result.deactivated += 1

    result.total_active = len(seen)
    # Make every synced product orderable (link/create its Dish) so a customer can type
    # or tap it without manual wiring.
    result.linked, result.created = await _ensure_orderable_dishes(
        session, restaurant_id=restaurant_id, products=products
    )
    logger.info(
        "catalog sync restaurant %s: +%d ~%d -%d (%d active); dishes linked %d created %d",
        restaurant_id, result.added, result.updated, result.deactivated,
        result.total_active, result.linked, result.created,
    )
    return result


async def push_dishes_to_meta(session: AsyncSession, *, restaurant_id: int) -> SyncResult:
    """Push local dishes to the restaurant's Meta catalogue."""
    from app.menu.models import Dish, Menu

    rest = await session.get(Restaurant, restaurant_id)
    if rest is None:
        return SyncResult()
    settings_dict = rest.settings or {}
    catalog_id = (settings_dict.get("catalog_id") or "").strip()
    if not catalog_id:
        raise CatalogWriteError("Set a Catalog ID before pushing to Meta.")

    menu = await session.scalar(
        select(Menu)
        .where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
        .order_by(Menu.version.desc())
        .limit(1)
    )
    if menu is None:
        return SyncResult()

    dishes = list(
        (
            await session.scalars(
                select(Dish).where(
                    Dish.menu_id == menu.id,
                    Dish.is_available.is_(True),
                    Dish.price_aed.is_not(None),
                )
            )
        ).all()
    )

    app_settings = get_settings()
    base_url = app_settings.public_base_url.rstrip("/")
    image_link = app_settings.catalog_placeholder_image_url
    brand = rest.name or "Restaurant"

    requests: list[dict] = []
    pushed_dishes: list[Dish] = []
    for dish in dishes:
        if not dish.name or dish.price_aed is None:
            continue
        rid = (dish.catalog_retailer_id or "").strip() or _dish_retailer_id(
            dish.id, dish.dish_number
        )
        had_rid = bool((dish.catalog_retailer_id or "").strip())
        if not had_rid:
            dish.catalog_retailer_id = rid
        method = "UPDATE" if had_rid else "CREATE"
        product_link = f"{base_url}/r/{restaurant_id}/menu#{rid}"
        data = build_catalog_item_data(
            name=dish.name,
            description=dish.description,
            price_aed=Decimal(str(dish.price_aed)),
            category=dish.category,
            is_available=dish.is_available,
            restaurant_name=brand,
            product_link=product_link,
            image_link=image_link,
        )
        requests.append({"method": method, "retailer_id": rid, "data": data})
        pushed_dishes.append(dish)

    if not requests:
        return SyncResult()

    try:
        await push_products_batch(catalog_id, requests, wait_for_ingest=True)
    except CatalogWriteError as exc:
        result = SyncResult()
        result.push_errors = [str(exc)]
        raise

    mirror_added, mirror_updated = await _mirror_dishes_to_catalog(
        session, restaurant_id=restaurant_id, dishes=pushed_dishes
    )
    result = SyncResult()
    result.pushed = sum(1 for r in requests if r["method"] == "CREATE")
    result.push_updated = sum(1 for r in requests if r["method"] == "UPDATE")
    result.added = mirror_added
    result.updated = mirror_updated
    result.total_active = mirror_added + mirror_updated
    logger.info(
        "catalog push restaurant %s: +%d ~%d (mirror +%d ~%d)",
        restaurant_id,
        result.pushed,
        result.push_updated,
        mirror_added,
        mirror_updated,
    )
    return result


async def sync_full_bidirectional(
    session: AsyncSession, *, restaurant_id: int
) -> SyncResult:
    """Bidirectional sync: pull Meta → link → push all dishes → mirror → re-pull."""
    pull = await sync_catalog_from_meta(session, restaurant_id=restaurant_id)
    try:
        push = await push_dishes_to_meta(session, restaurant_id=restaurant_id)
    except CatalogWriteError:
        raise
    final = await sync_catalog_from_meta(session, restaurant_id=restaurant_id)
    final.pushed = push.pushed
    final.push_updated = push.push_updated
    final.push_errors = push.push_errors
    # Preserve first-pull link/create counts for the UI toast.
    final.linked = pull.linked
    final.created = pull.created
    return final


async def list_catalog_products(
    session: AsyncSession, *, restaurant_id: int, active_only: bool = False
) -> list[CatalogProduct]:
    """Synced products for the OPS catalogue view, newest-synced ordering by name."""
    stmt = select(CatalogProduct).where(CatalogProduct.restaurant_id == restaurant_id)
    if active_only:
        stmt = stmt.where(CatalogProduct.is_active.is_(True))
    stmt = stmt.order_by(CatalogProduct.category, CatalogProduct.name)
    return list((await session.scalars(stmt)).all())


async def is_catalog_fully_synced(session: AsyncSession, *, restaurant_id: int) -> bool:
    """True when every available priced dish is linked to an active catalogue row."""
    from app.menu.unified import build_unified_menu

    rest = await session.get(Restaurant, restaurant_id)
    catalog_id = ((rest.settings or {}).get("catalog_id") or "").strip() if rest else ""
    if not catalog_id:
        return False
    unified = await build_unified_menu(
        session, restaurant_id=restaurant_id, catalog_id=catalog_id
    )
    if unified.linked_count == 0:
        return False
    dish_only_available = [
        i for i in unified.items
        if i.link_status == "dish_only" and i.is_available and i.price_aed is not None
    ]
    return len(dish_only_available) == 0