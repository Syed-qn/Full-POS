"""Partner menu push/pull helpers (Phase 3)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.menu.models import Dish, Menu
from app.ordering.matching import normalize_name
from app.pos.mapper import _clean_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PartnerMenuItemInput:
    pos_id: str
    name: str
    price_aed: Decimal
    dish_number: int | None = None
    category: str | None = None
    description: str | None = None
    is_available: bool = True


@dataclass
class PartnerMenuUpsertResult:
    created: int = 0
    updated: int = 0
    images: int = 0
    errors: list[str] | None = None


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


async def upsert_partner_menu_items(
    session: AsyncSession,
    *,
    restaurant_id: int,
    items: list[PartnerMenuItemInput],
    publish: bool = True,
) -> PartnerMenuUpsertResult:
    """Bulk upsert dishes by ``pos_product_id``. Does NOT remove items missing from payload."""
    from app.menu.service import store_dish_image

    result = PartnerMenuUpsertResult(errors=[])
    if not items:
        return result

    menu = await _get_or_create_active_menu(session, restaurant_id)
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

    used_numbers = {
        n
        for n in (
            await session.scalars(
                select(Dish.dish_number).where(Dish.restaurant_id == restaurant_id)
            )
        ).all()
        if n is not None
    }

    for raw in items:
        pos_id = raw.pos_id.strip()
        if not pos_id:
            result.errors.append("item missing pos_id")
            continue
        if raw.price_aed <= 0:
            result.errors.append(f"{pos_id}: price must be positive")
            continue
        name = _clean_name(raw.name)
        if not name:
            result.errors.append(f"{pos_id}: name required")
            continue

        dish = owned.get(pos_id)
        if dish is not None:
            dish.name = name
            dish.name_normalized = normalize_name(name)
            dish.price_aed = raw.price_aed
            dish.category = raw.category
            dish.description = raw.description
            dish.is_available = raw.is_available
            dish.menu_id = menu.id
            if raw.dish_number is not None:
                dish.dish_number = raw.dish_number
            result.updated += 1
            continue

        dish_number = raw.dish_number
        if dish_number is None:
            next_number += 1
            dish_number = next_number
        while dish_number in used_numbers:
            dish_number += 1
        used_numbers.add(dish_number)

        dish = Dish(
            menu_id=menu.id,
            restaurant_id=restaurant_id,
            dish_number=dish_number,
            name=name,
            name_normalized=normalize_name(name),
            price_aed=raw.price_aed,
            category=raw.category,
            description=raw.description,
            is_available=raw.is_available,
            pos_product_id=pos_id,
        )
        try:
            from app.pos.images import generate_dish_image

            png = generate_dish_image(name)
            dish.image_url = await store_dish_image(
                session, restaurant_id=restaurant_id, content=png, content_type="image/png"
            )
            result.images += 1
        except Exception:  # noqa: BLE001
            logger.exception("partner menu image failed for %s", name)
        session.add(dish)
        owned[pos_id] = dish
        result.created += 1

    await session.flush()

    if publish:
        await _publish_menu_mirror(session, restaurant_id=restaurant_id)

    return result


async def patch_partner_menu_item(
    session: AsyncSession,
    *,
    restaurant_id: int,
    pos_id: str,
    price_aed: Decimal | None = None,
    is_available: bool | None = None,
    name: str | None = None,
    publish: bool = True,
) -> Dish | None:
    """Fast path for sold-out / price tweaks."""
    dish = await session.scalar(
        select(Dish).where(
            Dish.restaurant_id == restaurant_id,
            Dish.pos_product_id == pos_id.strip(),
        )
    )
    if dish is None:
        return None
    if name is not None:
        dish.name = _clean_name(name)
        dish.name_normalized = normalize_name(dish.name)
    if price_aed is not None:
        if price_aed <= 0:
            raise ValueError("price must be positive")
        dish.price_aed = price_aed
    if is_available is not None:
        dish.is_available = is_available
    await session.flush()
    if publish:
        await _publish_menu_mirror(session, restaurant_id=restaurant_id)
    return dish


async def _publish_menu_mirror(session: AsyncSession, *, restaurant_id: int) -> None:
    """Meta catalog push + OKF refresh (best-effort, mirrors POS sync tail)."""
    try:
        from app.catalog.sync_service import auto_publish_to_meta

        await auto_publish_to_meta(session, restaurant_id=restaurant_id)
    except Exception:  # noqa: BLE001
        logger.exception("partner menu Meta publish failed (restaurant %s)", restaurant_id)
    try:
        from app.okf.producer import refresh_okf_for_restaurant

        await refresh_okf_for_restaurant(session, restaurant_id=restaurant_id)
    except Exception:  # noqa: BLE001
        logger.exception("partner menu OKF refresh failed (restaurant %s)", restaurant_id)


async def get_partner_menu_sync_status(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
) -> dict:
    """Last POS pull breadcrumb + count of POS-owned dishes."""
    pos_count = await session.scalar(
        select(func.count())
        .select_from(Dish)
        .where(
            Dish.restaurant_id == restaurant.id,
            Dish.pos_product_id.is_not(None),
        )
    )
    last = (restaurant.settings or {}).get("pos_last_sync") or {}
    return {
        "pos_dish_count": int(pos_count or 0),
        "last_pos_pull": last,
    }


def queue_pos_menu_pull(restaurant_id: int) -> dict:
    """Enqueue a full Cratis/POS pull (Path B — menu-changed signal)."""
    from app.config import get_settings

    if get_settings().outbox_sync_delivery:
        return {"queued": False, "mode": "inprocess", "detail": "Use POST /api/v1/pos/sync"}
    from app.pos.worker import sync_pos_menu_task

    sync_pos_menu_task.apply_async(
        args=[restaurant_id], kwargs={"publish": True}, queue="maintenance"
    )
    return {"queued": True, "mode": "celery", "detail": "Full POS menu pull queued."}