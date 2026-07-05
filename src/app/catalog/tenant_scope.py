"""Tenant ownership for shared Meta catalogue containers (multi-restaurant WABA).

When Biryani and Lims share one ``catalog_id`` (Feasto), Meta's mirror and native UI
contain every tenant's products. Every code path that shows, sends, or grounds on the
menu must pass through these helpers — Pull, WhatsApp cards, text menu, LLM, OPS UI.

Performance: ``TenantCatalogGate`` preloads ownership in O(1) queries — never N+1 per
product. When only one tenant uses a ``catalog_id``, filtering is skipped entirely.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import CatalogProduct
from app.identity.models import Restaurant

DISH_RETAILER_ID = re.compile(r"^dish-(\d+)-")


@dataclass
class TenantCatalogGate:
    """Batched ownership lookups — one build, many O(1) ``owns()`` checks."""

    restaurant_id: int
    anchor_rids: frozenset[str] = field(default_factory=frozenset)
    linked_rids: frozenset[str] = field(default_factory=frozenset)
    dish_owners: dict[int, int] = field(default_factory=dict)

    def owns(self, retailer_id: str) -> bool:
        rid = (retailer_id or "").strip()
        if not rid:
            return False
        m = DISH_RETAILER_ID.match(rid)
        if m:
            return self.dish_owners.get(int(m.group(1))) == self.restaurant_id
        return rid in self.linked_rids


def _dish_ids_from_rids(retailer_ids: set[str]) -> set[int]:
    out: set[int] = set()
    for rid in retailer_ids:
        m = DISH_RETAILER_ID.match(rid)
        if m:
            out.add(int(m.group(1)))
    return out


async def build_tenant_catalog_gate(
    session: AsyncSession,
    restaurant_id: int,
    *,
    extra_retailer_ids: set[str] | None = None,
) -> TenantCatalogGate:
    """Preload dish owners + linked retailer_ids in a handful of queries."""
    from app.menu.models import Dish

    anchor_rids = await tenant_dish_retailer_ids(session, restaurant_id)
    linked_rows = await session.scalars(
        select(Dish.catalog_retailer_id).where(
            Dish.restaurant_id == restaurant_id,
            Dish.catalog_retailer_id.is_not(None),
        )
    )
    linked_rids = frozenset(r.strip() for r in linked_rows if r and r.strip())
    scan_rids = set(anchor_rids) | linked_rids | (extra_retailer_ids or set())
    dish_ids = _dish_ids_from_rids(scan_rids)
    dish_owners: dict[int, int] = {}
    if dish_ids:
        rows = await session.execute(
            select(Dish.id, Dish.restaurant_id).where(Dish.id.in_(dish_ids))
        )
        dish_owners = {int(did): int(rid) for did, rid in rows.all()}
    return TenantCatalogGate(
        restaurant_id=restaurant_id,
        anchor_rids=anchor_rids,
        linked_rids=linked_rids,
        dish_owners=dish_owners,
    )


async def product_belongs_to_restaurant(
    session: AsyncSession, *, restaurant_id: int, retailer_id: str
) -> bool:
    """True when a Meta product is owned by this tenant (not a sibling on shared Feasto)."""
    gate = await build_tenant_catalog_gate(
        session, restaurant_id, extra_retailer_ids={(retailer_id or "").strip()},
    )
    return gate.owns(retailer_id)


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


async def is_shared_catalog(session: AsyncSession, *, restaurant_id: int) -> bool:
    """True when this restaurant's catalog_id is used by more than one tenant."""
    from sqlalchemy import func, text

    rest = await session.get(Restaurant, restaurant_id)
    catalog_id = ((rest.settings or {}).get("catalog_id") or "").strip() if rest else ""
    if not catalog_id:
        return False
    n = await session.scalar(
        select(func.count())
        .select_from(Restaurant)
        .where(text("(settings->>'catalog_id') = :cid").bindparams(cid=catalog_id))
    )
    return int(n or 0) > 1


def filter_products_with_gate(
    products: list[CatalogProduct], gate: TenantCatalogGate
) -> list[CatalogProduct]:
    """In-memory filter using a prebuilt gate (no per-row DB)."""
    kept = [p for p in products if gate.owns((p.retailer_id or "").strip())]
    if gate.anchor_rids:
        kept = [p for p in kept if (p.retailer_id or "").strip() in gate.anchor_rids]
    return kept


async def filter_tenant_catalog_products(
    session: AsyncSession,
    *,
    restaurant_id: int,
    products: list[CatalogProduct],
) -> list[CatalogProduct]:
    """Drop sibling-tenant rows from a shared-catalog mirror (batched, not N+1)."""
    if not products:
        return products
    if not await is_shared_catalog(session, restaurant_id=restaurant_id):
        return products
    gate = await build_tenant_catalog_gate(
        session,
        restaurant_id,
        extra_retailer_ids={(p.retailer_id or "").strip() for p in products},
    )
    return filter_products_with_gate(products, gate)


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
    return catalog_id, synced


async def prune_foreign_dishes(
    session: AsyncSession, *, restaurant_id: int, gate: TenantCatalogGate | None = None
) -> int:
    """Drop or unlink dishes that are not tenant-owned (stale shared-catalog Pull)."""
    from app.menu.models import Dish
    from app.ordering.models import OrderItem

    if not await is_shared_catalog(session, restaurant_id=restaurant_id):
        return 0
    if gate is None:
        gate = await build_tenant_catalog_gate(session, restaurant_id)
    dishes = list(
        (
            await session.scalars(
                select(Dish).where(Dish.restaurant_id == restaurant_id)
            )
        ).all()
    )
    removed = 0
    for dish in dishes:
        rid = (dish.catalog_retailer_id or "").strip()
        if not rid or gate.owns(rid):
            continue
        has_orders = await session.scalar(
            select(OrderItem.id).where(OrderItem.dish_id == dish.id).limit(1)
        )
        if has_orders:
            dish.catalog_retailer_id = None
            dish.whatsapp_enabled = False
        else:
            await session.delete(dish)
            removed += 1
    if removed:
        await session.flush()
    return removed


async def list_tenant_catalog_products(
    session: AsyncSession, *, restaurant_id: int, active_only: bool = False
) -> list[CatalogProduct]:
    """OPS / unified-menu catalogue list — never includes sibling tenants on shared Feasto."""
    stmt = select(CatalogProduct).where(CatalogProduct.restaurant_id == restaurant_id)
    if active_only:
        stmt = stmt.where(CatalogProduct.is_active.is_(True))
    stmt = stmt.order_by(CatalogProduct.category, CatalogProduct.name)
    rows = list((await session.scalars(stmt)).all())
    return await filter_tenant_catalog_products(
        session, restaurant_id=restaurant_id, products=rows
    )