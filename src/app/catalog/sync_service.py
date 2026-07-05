"""Sync a restaurant's Meta Commerce catalogue into local ``catalog_products``.

Driven by the OPS "Sync from Meta" button (catalog mode only). Reads the catalogue
from Meta (``meta_client.fetch_catalog_products``) and upserts one row per
(restaurant, retailer_id), marking products that vanished from Meta as inactive.
"""
from __future__ import annotations

import logging
import re
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
    is_product_sendable,
    push_products_batch,
    upsert_product_sets,
)
from app.catalog.models import CatalogProduct
from app.config import get_settings
from app.identity.models import Restaurant

logger = logging.getLogger(__name__)

_DISH_RETAILER_ID = re.compile(r"^dish-(\d+)-")


async def _product_belongs_to_restaurant(
    session: AsyncSession, *, restaurant_id: int, retailer_id: str
) -> bool:
    """True when a Meta catalogue product is owned by this tenant.

    Shared WABA/catalogue containers (e.g. Feasto) hold every restaurant's products.
    Pull must not mirror sibling tenants' rows into this restaurant — only import when
    ``dish-{dish_id}-*`` references a ``dishes.id`` row for *this* restaurant, or the
    retailer_id is already linked to one of its dishes (non-standard ids).
    """
    rid = (retailer_id or "").strip()
    if not rid:
        return False
    from app.menu.models import Dish

    m = _DISH_RETAILER_ID.match(rid)
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


def _rest_token(settings_dict: dict | None) -> str | None:
    """A restaurant's OWN Meta access token (from onboarding its own Meta account), or
    None to fall back to the global system-user token. Catalogs created under the
    restaurant's own Business can only be reached with the restaurant's own token."""
    tok = ((settings_dict or {}).get("wa_access_token") or "").strip()
    return tok or None


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


async def _refresh_pushed_sendability(
    session: AsyncSession,
    *,
    restaurant_id: int,
    catalog_id: str,
    retailer_ids: list[str],
    token: str | None,
) -> None:
    """After a blocking push, flip mirror rows sendable when Meta has approved them."""
    from app.catalog.meta_client import fetch_catalog_products, is_product_sendable

    wanted = {r.strip() for r in retailer_ids if r and r.strip()}
    if not wanted:
        return
    try:
        meta_rows = await fetch_catalog_products(catalog_id, token=token)
    except CatalogReadError:
        return
    by_rid = {p.retailer_id: p for p in meta_rows if p.retailer_id in wanted}
    for rid, mp in by_rid.items():
        row = await session.scalar(
            select(CatalogProduct).where(
                CatalogProduct.restaurant_id == restaurant_id,
                CatalogProduct.retailer_id == rid,
            ).limit(1)
        )
        if row is None:
            continue
        row.is_sendable = is_product_sendable(mp)
        row.review_status = (
            (mp.review_status or "").strip().lower() or None
            if row.is_sendable
            else "in_review"
        )
        if mp.image_url:
            row.image_url = mp.image_url


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
        is_new = row is None
        if row is None:
            row = CatalogProduct(restaurant_id=restaurant_id, retailer_id=rid)
            session.add(row)
            added += 1
        else:
            updated += 1
        old_image = (row.image_url or "").strip()
        row.name = dish.name
        row.price_aed = dish.price_aed
        row.currency = "AED"
        row.availability = "in stock" if dish.is_available else "out of stock"
        row.category = dish.category
        row.is_active = dish.is_available
        new_image = (getattr(dish, "image_url", None) or "").strip()
        if new_image:
            row.image_url = dish.image_url
        # A just-pushed product (or one whose image changed) must be RE-FETCHED by Meta
        # before WhatsApp can send it — keep it "in review" until the next Sync confirms
        # the image is on Meta's CDN. Don't reset products that were already live and
        # whose image is unchanged (so editing one dish never knocks others off WhatsApp).
        if is_new or (new_image and new_image != old_image):
            row.is_sendable = False
            row.review_status = "in_review"
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

    products = await fetch_catalog_products(catalog_id, token=_rest_token(settings))
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
        if not await _product_belongs_to_restaurant(
            session, restaurant_id=restaurant_id, retailer_id=p.retailer_id
        ):
            continue
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
        # Only LINK (make sendable on WhatsApp) once Meta has fetched the image onto its
        # CDN and approved the product; otherwise keep it "in review" so the product_list
        # message can never fail with #131009.
        row.is_sendable = is_product_sendable(p)
        row.review_status = (
            (p.review_status or "").strip().lower() or None
            if row.is_sendable
            else "in_review"
        )
        row.synced_at = now

    # Products that disappeared from Meta → DELETE them here too (delete is delete): drop
    # the catalogue mirror row AND the linked dish. Exception: a dish with past order
    # history can't be hard-deleted without corrupting those orders (FK), so it is instead
    # unlinked + turned off for WhatsApp (kept in the menu, off the catalogue).
    from app.audit import record_audit
    from app.menu.models import Dish
    from app.ordering.models import OrderItem

    for retailer_id, row in existing.items():
        if retailer_id in seen:
            continue
        result.deactivated += 1
        dish = await session.scalar(
            select(Dish).where(
                Dish.restaurant_id == restaurant_id,
                Dish.catalog_retailer_id == retailer_id,
            ).limit(1)
        )
        if dish is not None:
            has_orders = await session.scalar(
                select(OrderItem.id).where(OrderItem.dish_id == dish.id).limit(1)
            )
            if has_orders:
                # Preserve order history — unlink + turn off instead of hard-deleting.
                dish.catalog_retailer_id = None
                dish.whatsapp_enabled = False
                await record_audit(
                    session, actor="meta-sync", restaurant_id=restaurant_id,
                    entity="dish", entity_id=str(dish.id),
                    action="whatsapp_unlinked_meta_deleted",
                    before={"catalog_retailer_id": retailer_id},
                    after={"whatsapp_enabled": False, "reason": "deleted in Meta; has orders"},
                )
            else:
                await record_audit(
                    session, actor="meta-sync", restaurant_id=restaurant_id,
                    entity="dish", entity_id=str(dish.id), action="removed",
                    before={"name": dish.name, "reason": "deleted in Meta"},
                )
                await session.delete(dish)
        await session.delete(row)

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


async def push_dishes_to_meta(
    session: AsyncSession, *, restaurant_id: int, wait_for_ingest: bool = True
) -> SyncResult:
    """Push local dishes to the restaurant's Meta catalogue.

    ``wait_for_ingest`` True (manual Publish): block until Meta finishes ingesting so the
    UI toast/counts are accurate. False (auto-publish on a dish edit): fire-and-forget so
    the manager's edit doesn't block on Meta and rapid edits don't pile up overlapping
    in-flight batches.
    """
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
                    Dish.meta_status == "active",
                    # Manager turned this dish OFF for WhatsApp → never publish it.
                    Dish.whatsapp_enabled.is_(True),
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
    seen_rids: set[str] = set()
    for dish in dishes:
        if not dish.name or dish.price_aed is None:
            continue
        rid = (dish.catalog_retailer_id or "").strip() or _dish_retailer_id(
            dish.id, dish.dish_number
        )
        # Meta rejects a whole items_batch if any retailer_id repeats. Two dishes can
        # collide on the same catalog_retailer_id (e.g. both name-matched to one Meta
        # product in an earlier sync). Push the first, skip the rest, and unlink the
        # duplicate locally so it gets its own id on the next push instead of colliding.
        if rid in seen_rids:
            logger.warning(
                "skipping dish %s (%s): duplicate retailer_id %s in push batch",
                dish.id, dish.name, rid,
            )
            if (dish.catalog_retailer_id or "").strip() == rid:
                dish.catalog_retailer_id = None
            continue
        seen_rids.add(rid)
        had_rid = bool((dish.catalog_retailer_id or "").strip())
        if not had_rid:
            dish.catalog_retailer_id = rid
        # Always UPDATE (the batch is sent with allow_upsert=True, so UPDATE creates the
        # item if missing and updates it if present). Using CREATE for a generated id that
        # ALREADY exists in Meta — e.g. a dish that was previously unlinked locally but
        # whose Meta product still exists — makes Meta reject the whole batch with
        # "Duplicate retailer_id in batch api call". UPDATE/upsert never collides.
        method = "UPDATE"
        product_link = f"{base_url}/r/{restaurant_id}/menu#{rid}"
        # Per-dish photo (Meta REQUIRES an image); fall back to the shared placeholder
        # only when this dish has none, so a push never fails for a missing image.
        dish_image = (getattr(dish, "image_url", None) or "").strip() or image_link
        sale_price = getattr(dish, "sale_price_aed", None)
        data = build_catalog_item_data(
            name=dish.name,
            description=dish.description,
            price_aed=Decimal(str(dish.price_aed)),
            category=dish.category,
            is_available=dish.is_available,
            restaurant_name=brand,
            product_link=product_link,
            image_link=dish_image,
            sale_price_aed=Decimal(str(sale_price)) if sale_price is not None else None,
            fb_product_category=getattr(dish, "fb_product_category", None),
            condition=getattr(dish, "condition", None),
            meta_status=getattr(dish, "meta_status", None),
            brand=getattr(dish, "brand", None),
        )
        # _was_linked: did this dish already have a Meta link before this push? Used only
        # for the UI toast (new vs updated); the wire method is always UPDATE/upsert.
        requests.append({"method": method, "retailer_id": rid, "data": data,
                         "_was_linked": had_rid})
        pushed_dishes.append(dish)

    if not requests:
        return SyncResult()

    try:
        await push_products_batch(
            catalog_id, requests, wait_for_ingest=wait_for_ingest,
            token=_rest_token(settings_dict),
        )
    except CatalogWriteError as exc:
        result = SyncResult()
        result.push_errors = [str(exc)]
        raise

    mirror_added, mirror_updated = await _mirror_dishes_to_catalog(
        session, restaurant_id=restaurant_id, dishes=pushed_dishes
    )
    if wait_for_ingest:
        await _refresh_pushed_sendability(
            session,
            restaurant_id=restaurant_id,
            catalog_id=catalog_id,
            retailer_ids=[(d.catalog_retailer_id or "").strip() for d in pushed_dishes],
            token=_rest_token(settings_dict),
        )
    result = SyncResult()
    result.pushed = sum(1 for r in requests if not r.get("_was_linked"))
    result.push_updated = sum(1 for r in requests if r.get("_was_linked"))
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


async def auto_publish_to_meta(session: AsyncSession, *, restaurant_id: int) -> SyncResult:
    """Best-effort: push the restaurant's dishes to Meta so every available, priced
    dish becomes a WhatsApp catalogue product automatically — no manual "Sync" click.

    Called after menu activation. Silently no-ops when there's no catalog_id/token
    (dev, or a restaurant that hasn't connected Meta yet) or if Meta is unreachable;
    publishing must NEVER block or fail the manager's menu activation. Caller commits.
    """
    rest = await session.get(Restaurant, restaurant_id)
    catalog_id = ((rest.settings or {}).get("catalog_id") or "").strip() if rest else ""
    if not catalog_id:
        return SyncResult()  # Meta not connected — nothing to publish to.
    try:
        # Fire-and-forget: don't block the manager's dish edit on Meta ingest, and avoid
        # overlapping in-flight batches when several edits happen quickly.
        return await push_dishes_to_meta(
            session, restaurant_id=restaurant_id, wait_for_ingest=False
        )
    except (CatalogReadError, CatalogWriteError) as exc:
        logger.warning("auto-publish to Meta skipped for restaurant %s: %s", restaurant_id, exc)
        return SyncResult()


# Strong refs to detached background pushes so the event loop can't GC them mid-run.
_BG_PUBLISH_TASKS: set = set()


def schedule_auto_publish(restaurant_id: int) -> None:
    """Fire-and-forget the Meta catalogue push on its OWN DB session, off the caller's
    request path. Meta HTTP carries 30-60s timeouts, so awaiting it inline stalls the
    manager's action (a dish save, or Confirm & Activate). Best-effort: failures are
    swallowed and re-attempted on the next mutation/activation. No-ops when there's no
    running event loop (e.g. a sync script)."""
    import asyncio

    async def _run() -> None:
        from app.db import async_session_factory

        try:
            async with async_session_factory() as session:
                await auto_publish_to_meta(session, restaurant_id=restaurant_id)
                await session.commit()
        except Exception:  # noqa: BLE001 — a background push must never surface
            pass

    try:
        task = asyncio.create_task(_run())
    except RuntimeError:
        return  # no running loop — skip the background push
    _BG_PUBLISH_TASKS.add(task)
    task.add_done_callback(_BG_PUBLISH_TASKS.discard)


async def sync_collections(session: AsyncSession, *, restaurant_id: int) -> dict:
    """Push one Meta product set ("collection") per dish category so the native WhatsApp
    catalogue groups the menu by category. Builds ``category -> [retailer_id]`` from the
    restaurant's published dishes (those with a ``catalog_retailer_id`` and a category)
    and upserts the sets. Best-effort: returns a skip marker rather than raising when Meta
    isn't connected. Caller commits (no DB writes here, but keep the contract uniform)."""
    rest = await session.get(Restaurant, restaurant_id)
    catalog_id = ((rest.settings or {}).get("catalog_id") or "").strip() if rest else ""
    if not catalog_id:
        return {"created": 0, "updated": 0, "failed": 0, "skipped": "no catalog_id"}

    from app.menu.models import Dish

    rows = (
        await session.execute(
            select(Dish.category, Dish.catalog_retailer_id).where(
                Dish.restaurant_id == restaurant_id,
                Dish.catalog_retailer_id.is_not(None),
                Dish.category.is_not(None),
            )
        )
    ).all()
    groups: dict[str, list[str]] = {}
    for cat, rid in rows:
        name = (cat or "").strip()
        if name and rid:
            groups.setdefault(name, []).append(rid)
    if not groups:
        return {"created": 0, "updated": 0, "failed": 0, "skipped": "no categorised dishes"}
    return await upsert_product_sets(
        catalog_id, groups, token=_rest_token(rest.settings if rest else None)
    )


async def unpublish_from_meta(
    session: AsyncSession, *, restaurant_id: int, retailer_id: str
) -> bool:
    """Best-effort: remove a single product from the Meta catalogue (and the local
    mirror) when its dish is deleted, so it stops showing as a WhatsApp card. No
    catalog_id/token or Meta error must ever fail the manager's delete. Caller commits.
    Returns True if a Meta DELETE was sent."""
    rid = (retailer_id or "").strip()
    if not rid:
        return False
    rest = await session.get(Restaurant, restaurant_id)
    catalog_id = ((rest.settings or {}).get("catalog_id") or "").strip() if rest else ""

    # Drop the local mirror row regardless (the dish is gone locally).
    row = await session.scalar(
        select(CatalogProduct).where(
            CatalogProduct.restaurant_id == restaurant_id,
            CatalogProduct.retailer_id == rid,
        ).limit(1)
    )
    if row is not None:
        await session.delete(row)

    if not catalog_id:
        return False
    try:
        await push_products_batch(
            catalog_id, [{"method": "DELETE", "retailer_id": rid, "data": {}}],
            wait_for_ingest=False,
            token=_rest_token(rest.settings if rest else None),
        )
        return True
    except (CatalogReadError, CatalogWriteError) as exc:
        logger.warning("Meta unpublish skipped for restaurant %s rid %s: %s", restaurant_id, rid, exc)
        return False


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