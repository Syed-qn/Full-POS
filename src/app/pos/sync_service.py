"""Sync a restaurant's POS menu into the dishes table (and on to WhatsApp).

Self-contained: it only ever creates/updates/removes dishes it OWNS — those tagged with
``pos_product_id``. Manually-managed dishes (no ``pos_product_id``) are never touched, so
this lives alongside the normal menu flows without disturbing them.

Flow: fetch POS menu -> map sellable items -> upsert by ``pos_product_id`` into the active
menu (generating a name-based image for new dishes) -> reconcile items removed from POS ->
auto-publish to Meta so everything shows on the WhatsApp catalogue.

Local-only fields (image_url, sale_price_aed, whatsapp_enabled, catalog_retailer_id) are
PRESERVED across syncs — POS only owns name/price/category/description.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.menu.models import Dish, Menu
from app.ordering.matching import normalize_name
from app.pos.factory import get_pos_provider
from app.pos.mapper import map_pos_menu
from app.pos.port import PosProvider

logger = logging.getLogger(__name__)


class PosConfigError(RuntimeError):
    """Raised when a restaurant has no POS account/location configured."""


@dataclass
class PosSyncResult:
    fetched: int = 0       # sellable products returned by POS
    created: int = 0       # new dishes created
    updated: int = 0       # existing POS dishes updated
    deactivated: int = 0   # dishes removed in POS (deleted or turned off)
    images: int = 0        # name-based images generated
    skipped_empty: bool = False  # POS returned nothing → sync aborted (no wipe)
    errors: list[str] = field(default_factory=list)


def _pos_config(rest: Restaurant | None) -> tuple[str, str, str | None]:
    s = (rest.settings or {}) if rest is not None else {}
    account = (s.get("pos_account") or "").strip()
    location = (s.get("pos_location") or "").strip()
    base_url = (s.get("pos_base_url") or "").strip() or None
    if not account or not location:
        raise PosConfigError("Set the POS account and location before syncing.")
    return account, location, base_url


async def _get_or_create_active_menu(session: AsyncSession, restaurant_id: int) -> Menu:
    menu = await session.scalar(
        select(Menu)
        .where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
        .order_by(Menu.version.desc())
        .limit(1)
    )
    if menu is None:
        menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
        session.add(menu)
        await session.flush()
    return menu


async def sync_menu_from_pos(
    session: AsyncSession,
    *,
    restaurant_id: int,
    provider: PosProvider | None = None,
    limit: int | None = None,
    publish: bool = True,
) -> PosSyncResult:
    """Pull the POS menu and mirror it into dishes. Caller commits. Best-effort image
    generation; a single image failure never aborts the sync.

    ``limit`` caps how many sellable items are synced (for a safe first/validation run).
    ``publish`` False skips the Meta push (dishes created locally only — a dry run).
    """
    from app.menu.service import store_dish_image

    rest = await session.get(Restaurant, restaurant_id)
    account, location, base_url = _pos_config(rest)
    provider = provider or get_pos_provider()

    pos_menu = await provider.fetch_menu(account=account, location=location, base_url=base_url)
    records = map_pos_menu(pos_menu)
    if limit is not None and limit >= 0:
        records = records[:limit]
    result = PosSyncResult(fetched=len(records))

    # SAFETY: never wipe the live menu if the POS returns nothing (outage / bad response).
    if not records:
        result.skipped_empty = True
        logger.warning(
            "POS sync for restaurant %s returned 0 sellable items — aborting (no wipe)",
            restaurant_id,
        )
        return result

    menu = await _get_or_create_active_menu(session, restaurant_id)

    # Dishes THIS module owns, keyed by pos_product_id.
    owned = {
        d.pos_product_id: d
        for d in (
            await session.scalars(
                select(Dish).where(
                    Dish.restaurant_id == restaurant_id,
                    Dish.pos_product_id.is_not(None),
                )
            )
        ).all()
    }
    next_number = (
        await session.scalar(
            select(func.max(Dish.dish_number)).where(Dish.restaurant_id == restaurant_id)
        )
    ) or 0

    seen: set[str] = set()
    for rec in records:
        seen.add(rec.pos_product_id)
        dish = owned.get(rec.pos_product_id)
        if dish is not None:
            # POS owns name/price/category/description; local fields are preserved.
            dish.name = rec.name
            dish.name_normalized = normalize_name(rec.name)
            dish.price_aed = rec.price_aed
            dish.category = rec.category
            dish.description = rec.description
            dish.menu_id = menu.id
            result.updated += 1
            continue
        next_number += 1
        dish = Dish(
            menu_id=menu.id,
            restaurant_id=restaurant_id,
            dish_number=next_number,
            name=rec.name,
            name_normalized=normalize_name(rec.name),
            price_aed=rec.price_aed,
            category=rec.category,
            description=rec.description,
            is_available=True,
            pos_product_id=rec.pos_product_id,
        )
        # Generate a name-based image so the dish has a real product photo on WhatsApp.
        try:
            from app.pos.images import generate_dish_image

            png = generate_dish_image(rec.name)
            dish.image_url = await store_dish_image(
                session, restaurant_id=restaurant_id, content=png, content_type="image/png"
            )
            result.images += 1
        except Exception:  # noqa: BLE001 - image is best-effort; placeholder used on push
            logger.exception("POS image generation failed for %s", rec.name)
        session.add(dish)
        result.created += 1

    # Items removed from POS → remove here too. A dish with order history can't be
    # hard-deleted (FK), so it is deactivated + unlinked instead.
    from app.ordering.models import OrderItem

    for pid, dish in owned.items():
        if pid in seen:
            continue
        has_orders = await session.scalar(
            select(OrderItem.id).where(OrderItem.dish_id == dish.id).limit(1)
        )
        if has_orders:
            dish.is_available = False
            dish.whatsapp_enabled = False
            dish.catalog_retailer_id = None
        else:
            await session.delete(dish)
        result.deactivated += 1

    await session.flush()
    # Persist the menu mirror BEFORE the best-effort steps, so a publish/grounding hiccup
    # can be rolled back in isolation without losing the synced dishes.
    await session.commit()
    logger.info(
        "POS sync restaurant %s: +%d ~%d -%d (%d images)",
        restaurant_id, result.created, result.updated, result.deactivated, result.images,
    )

    # Publish to Meta so the POS menu shows on WhatsApp (best-effort, never fail the sync).
    if publish:
        try:
            from app.catalog.sync_service import auto_publish_to_meta

            await auto_publish_to_meta(session, restaurant_id=restaurant_id)
            await session.commit()
        except Exception:  # noqa: BLE001
            await session.rollback()
            logger.exception("auto-publish after POS sync failed (restaurant %s)", restaurant_id)

    # Refresh the bot's grounding so it answers from the new menu.
    try:
        from app.okf.producer import refresh_okf_for_restaurant

        await refresh_okf_for_restaurant(session, restaurant_id=restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
        logger.exception("OKF refresh after POS sync failed (restaurant %s)", restaurant_id)

    return result
