"""Sync a restaurant's Meta Commerce catalogue into local ``catalog_products``.

Driven by the OPS "Sync from Meta" button (catalog mode only). Reads the catalogue
from Meta (``meta_client.fetch_catalog_products``) and upserts one row per
(restaurant, retailer_id), marking products that vanished from Meta as inactive.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.meta_client import CatalogReadError, fetch_catalog_products
from app.catalog.models import CatalogProduct
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


async def list_catalog_products(
    session: AsyncSession, *, restaurant_id: int, active_only: bool = False
) -> list[CatalogProduct]:
    """Synced products for the OPS catalogue view, newest-synced ordering by name."""
    stmt = select(CatalogProduct).where(CatalogProduct.restaurant_id == restaurant_id)
    if active_only:
        stmt = stmt.where(CatalogProduct.is_active.is_(True))
    stmt = stmt.order_by(CatalogProduct.category, CatalogProduct.name)
    return list((await session.scalars(stmt)).all())
