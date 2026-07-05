"""Tenant ownership for shared Meta catalogue containers (multi-restaurant WABA).

When Biryani and Lims share one ``catalog_id`` (Feasto), Meta's mirror and native UI
contain every tenant's products. Every code path that shows, sends, or grounds on the
menu must pass through these helpers — Pull, WhatsApp cards, text menu, LLM, OPS UI.
"""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import CatalogProduct
from app.identity.models import Restaurant

DISH_RETAILER_ID = re.compile(r"^dish-(\d+)-")


async def product_belongs_to_restaurant(
    session: AsyncSession, *, restaurant_id: int, retailer_id: str
) -> bool:
    """True when a Meta product is owned by this tenant (not a sibling on shared Feasto)."""
    rid = (retailer_id or "").strip()
    if not rid:
        return False
    from app.menu.models import Dish

    m = DISH_RETAILER_ID.match(rid)
    if m:
        dish_id = int(m.group(1))
        owner = await session.scalar(
            select(Dish.restaurant_id).where(Dish.id == dish_id).limit(1)
        )
        return owner == restaurant_id
    linked = await session.scalar(
        select(Dish.id).where(
            Dish.restaurant_id == restaurant_id,
            Dish.catalog_retailer_id == rid,
        ).limit(1)
    )
    return linked is not None


async def tenant_dish_retailer_ids(
    session: AsyncSession, restaurant_id: int
) -> frozenset[str]:
    """Retailer ids on this tenant's live, WhatsApp-enabled dishes (publish anchor)."""
    from app.menu.models import Dish, Menu

    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if menu is None:
        return frozenset()
    rows = await session.scalars(
        select(Dish.catalog_retailer_id).where(
            Dish.menu_id == menu.id,
            Dish.is_available.is_(True),
            Dish.meta_status == "active",
            Dish.whatsapp_enabled.is_(True),
            Dish.catalog_retailer_id.is_not(None),
        )
    )
    return frozenset(r.strip() for r in rows if r and r.strip())


async def filter_tenant_catalog_products(
    session: AsyncSession,
    *,
    restaurant_id: int,
    products: list[CatalogProduct],
) -> list[CatalogProduct]:
    """Drop sibling-tenant rows from a shared-catalog mirror."""
    kept: list[CatalogProduct] = []
    for p in products:
        rid = (p.retailer_id or "").strip()
        if rid and await product_belongs_to_restaurant(
            session, restaurant_id=restaurant_id, retailer_id=rid
        ):
            kept.append(p)
    return kept


async def count_tenants_on_catalog(session: AsyncSession, catalog_id: str) -> int:
    """How many restaurants share this Meta ``catalog_id``."""
    cid = (catalog_id or "").strip()
    if not cid:
        return 0
    n = 0
    for rest in (await session.scalars(select(Restaurant))).all():
        if ((rest.settings or {}).get("catalog_id") or "").strip() == cid:
            n += 1
    return n


async def is_shared_catalog(session: AsyncSession, *, restaurant_id: int) -> bool:
    """True when this restaurant's catalog_id is used by more than one tenant."""
    rest = await session.get(Restaurant, restaurant_id)
    catalog_id = ((rest.settings or {}).get("catalog_id") or "").strip() if rest else ""
    if not catalog_id:
        return False
    return await count_tenants_on_catalog(session, catalog_id) > 1


async def native_catalog_view_allowed(
    session: AsyncSession, *, restaurant_id: int, settings: dict | None
) -> bool:
    """Per-tenant flag only. Lims keeps ``catalog_native_view=false`` (filtered cards);
    Biryani keeps ``true`` (native full-menu button) even when both share Feasto."""
    return bool((settings or {}).get("catalog_native_view"))


async def load_tenant_catalog_mirror(
    session: AsyncSession, restaurant_id: int
) -> tuple[str | None, list[CatalogProduct]]:
    """Active mirror rows for this tenant — filtered + dish-anchored when dishes are pushed."""
    rest = await session.get(Restaurant, restaurant_id)
    settings = (rest.settings or {}) if rest is not None else {}
    catalog_id = (settings.get("catalog_id") or "").strip()
    if not catalog_id:
        return None, []

    synced = list(
        (
            await session.scalars(
                select(CatalogProduct)
                .where(
                    CatalogProduct.restaurant_id == restaurant_id,
                    CatalogProduct.is_active.is_(True),
                )
                .order_by(CatalogProduct.category, CatalogProduct.name)
            )
        ).all()
    )
    synced = await filter_tenant_catalog_products(
        session, restaurant_id=restaurant_id, products=synced
    )
    anchor_rids = await tenant_dish_retailer_ids(session, restaurant_id)
    if anchor_rids:
        synced = [p for p in synced if (p.retailer_id or "").strip() in anchor_rids]
    return catalog_id, synced


async def list_tenant_catalog_products(
    session: AsyncSession, *, restaurant_id: int, active_only: bool = False
) -> list[CatalogProduct]:
    """OPS / unified-menu catalogue list — never includes sibling tenants on shared Feasto."""
    stmt = select(CatalogProduct).where(CatalogProduct.restaurant_id == restaurant_id)
    if active_only:
        stmt = stmt.where(CatalogProduct.is_active.is_(True))
    stmt = stmt.order_by(CatalogProduct.category, CatalogProduct.name)
    rows = list((await session.scalars(stmt)).all())
    filtered = await filter_tenant_catalog_products(
        session, restaurant_id=restaurant_id, products=rows
    )
    anchor_rids = await tenant_dish_retailer_ids(session, restaurant_id)
    if anchor_rids:
        filtered = [p for p in filtered if (p.retailer_id or "").strip() in anchor_rids]
    return filtered