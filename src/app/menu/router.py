import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.llm.factory import get_menu_extractor
from app.llm.port import MenuExtractor, UploadedFile
from app.menu import service
from app.menu.models import Dish, Menu
from app.ordering.matching import normalize_name
from app.menu.schemas import (
    AvailabilityIn,
    DiffOut,
    DishIn,
    DishOut,
    DishPatch,
    MenuOut,
    MenuWithDiffOut,
    WhatsappToggleIn,
    serialize_variants,
)
from app.menu.service import MenuIncompleteError
from app.menu.unified import UnifiedMenuOut, build_unified_menu
from app.catalog.sync_service import auto_publish_to_meta, unpublish_from_meta
from app.okf.producer import refresh_okf_for_restaurant


async def _refresh_grounding(session: AsyncSession, restaurant_id: int) -> None:
    """Run after a dish mutation on these inline endpoints (which bypass activate_menu):
      1. rebuild OKF menu/policy docs so the bot grounds on the live menu;
      2. auto-publish the menu to the Meta catalogue so the dish edit shows on WhatsApp.
    Both are best-effort — neither a grounding refresh nor a Meta push may fail the
    manager's edit. Each is committed independently so one failing can't undo the other."""
    try:
        await refresh_okf_for_restaurant(session, restaurant_id=restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
    try:
        await auto_publish_to_meta(session, restaurant_id=restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()

router = APIRouter(prefix="/api/v1", tags=["menu"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


async def _load_menu(
    menu_id: int,
    restaurant: Restaurant,
    session: AsyncSession,
) -> Menu:
    menu = await session.get(Menu, menu_id)
    if menu is None or menu.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "menu not found")
    return menu


@router.post("/menus", response_model=MenuWithDiffOut, status_code=201)
async def upload_menu(
    files: list[UploadFile],
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
    extractor: MenuExtractor = Depends(get_menu_extractor),
):
    uploaded = []
    for f in files:
        content = await f.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"File '{f.filename}' exceeds maximum size of "
                f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )
        # Rewind so downstream readers (if any) can re-read
        f.file = io.BytesIO(content)
        uploaded.append(
            UploadedFile(
                filename=f.filename or "file",
                content=content,
                mime=f.content_type or "application/octet-stream",
            )
        )
    try:
        menu, report = await service.upload_with_diff(
            session, restaurant_id=restaurant.id, files=uploaded, extractor=extractor
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"menu extraction failed: {exc}")
    out = MenuWithDiffOut.model_validate(menu)
    if report is not None:
        out.diff_vs_active = DiffOut(
            price_changes=[
                {**c, "old_price": str(c["old_price"]), "new_price": str(c["new_price"])}
                for c in report.price_changes
            ],
            added=[d.model_dump(mode="json") for d in report.added],
            removed=report.removed,
            conflicts=report.conflicts,
        )
    return out


@router.get("/menu/unified", response_model=UnifiedMenuOut)
async def get_unified_menu(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Single menu view: dishes + Meta catalogue products with link status."""
    settings = restaurant.settings or {}
    catalog_id = (settings.get("catalog_id") or "").strip()
    return await build_unified_menu(
        session, restaurant_id=restaurant.id, catalog_id=catalog_id
    )


@router.get("/menus/active", response_model=MenuOut)
async def get_active_menu(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Return the currently active menu with all dishes for this restaurant."""
    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant.id,
            Menu.status == "active",
        )
    )
    if not menu:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active menu")
    await session.refresh(menu)
    return menu


@router.get("/menus/{menu_id}", response_model=MenuOut)
async def get_menu(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await _load_menu(menu_id, restaurant, session)


@router.post("/dishes/image", status_code=201)
async def upload_dish_image(
    file: UploadFile,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Upload a dish photo for the Meta catalogue. Returns a public ``/media/<path>``
    URL to store on the dish (``image_url``) — Meta fetches it as the product image."""
    if (file.content_type or "") not in service.DISH_IMAGE_MIMES:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Dish photo must be JPG or PNG"
        )
    content = await file.read()
    if len(content) > service.MAX_DISH_IMAGE_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Image exceeds 5 MB")
    url = await service.store_dish_image(
        session,
        restaurant_id=restaurant.id,
        content=content,
        content_type=file.content_type or "image/jpeg",
    )
    await session.commit()
    return {"url": url}


@router.post("/menus/{menu_id}/dishes", response_model=DishOut, status_code=201)
async def add_dish(
    menu_id: int,
    body: DishIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dup = await session.scalar(
        select(Dish).where(Dish.menu_id == menu.id, Dish.dish_number == body.dish_number)
    )
    if dup:
        raise HTTPException(status.HTTP_409_CONFLICT, "dish number already in menu")
    data = body.model_dump()
    # JSONB can't store Decimal — store variants with string prices (canonical shape).
    data["variants"] = serialize_variants(body.variants)
    dish = Dish(menu_id=menu.id, restaurant_id=restaurant.id, **data)
    dish.name_normalized = normalize_name(dish.name)
    session.add(dish)
    await session.flush()
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="added", after=body.model_dump(mode="json"),
    )
    await session.commit()
    await session.refresh(dish)
    await _refresh_grounding(session, restaurant.id)
    return dish


@router.patch("/menus/{menu_id}/dishes/{dish_id}", response_model=DishOut)
async def patch_dish(
    menu_id: int,
    dish_id: int,
    body: DishPatch,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.menu_id != menu.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    changes = body.model_dump(exclude_unset=True)
    if "variants" in changes:
        # Serialize to canonical JSONB shape (string prices); None means "clear".
        changes["variants"] = serialize_variants(body.variants or [])
    if "dish_number" in changes:
        dup = await session.scalar(
            select(Dish).where(
                Dish.menu_id == menu.id,
                Dish.dish_number == changes["dish_number"],
                Dish.id != dish.id,
            )
        )
        if dup:
            raise HTTPException(status.HTTP_409_CONFLICT, "dish number already in menu")
    before = {k: str(getattr(dish, k)) for k in changes}
    for key, value in changes.items():
        setattr(dish, key, value)
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="edited", before=before,
        after={k: str(v) for k, v in changes.items()},
    )
    await session.commit()
    await session.refresh(dish)
    await _refresh_grounding(session, restaurant.id)
    return dish


@router.delete("/menus/{menu_id}/dishes/{dish_id}", status_code=204)
async def delete_dish(
    menu_id: int,
    dish_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.menu_id != menu.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    from app.catalog.meta_client import _dish_retailer_id
    from app.ordering.models import OrderItem

    rid = restaurant.id  # capture before expire_all expires the restaurant row
    # Capture EVERY Content ID this dish could exist under in Meta, before the delete:
    #   * its stored link (catalog_retailer_id — set on sync/push), and
    #   * the deterministic push id (dish-<id>-<number>) it would have been pushed under
    #     even if the link was never persisted (e.g. an auto-push that failed pre-fix).
    # Deleting under both guarantees the product is removed from Commerce Manager so it
    # also disappears from the WhatsApp catalogue — not just hidden locally.
    retailer_ids = {
        r for r in (
            (dish.catalog_retailer_id or "").strip(),
            _dish_retailer_id(dish.id, dish.dish_number),
        ) if r
    }
    # A dish with order history can't be hard-deleted (order_items FK → would corrupt past
    # orders). In that case DEACTIVATE it instead: unlink, turn WhatsApp off, mark
    # unavailable, keep the row. Otherwise hard-delete. Either way it's removed from Meta.
    has_orders = await session.scalar(
        select(OrderItem.id).where(OrderItem.dish_id == dish.id).limit(1)
    )
    if has_orders:
        dish.is_available = False
        dish.whatsapp_enabled = False
        dish.catalog_retailer_id = None
        await record_audit(
            session, actor="manager", restaurant_id=restaurant.id, entity="dish",
            entity_id=str(dish.id), action="deactivated",
            before={"dish_number": dish.dish_number, "name": dish.name},
            after={"reason": "deleted in OPS; has order history → deactivated"},
        )
    else:
        await record_audit(
            session, actor="manager", restaurant_id=restaurant.id, entity="dish",
            entity_id=str(dish.id), action="removed",
            before={"dish_number": dish.dish_number, "name": dish.name},
        )
        await session.delete(dish)
    await session.commit()
    session.expire_all()
    # Remove it from the Meta catalogue too so it stops showing as a WhatsApp card.
    for retailer_id in retailer_ids:
        try:
            await unpublish_from_meta(session, restaurant_id=rid, retailer_id=retailer_id)
            await session.commit()
        except Exception:  # noqa: BLE001 — unpublish must never fail the delete
            await session.rollback()
    await _refresh_grounding(session, rid)


@router.patch("/dishes/{dish_id}/availability", response_model=DishOut)
async def toggle_availability(
    dish_id: int,
    body: AvailabilityIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    before = {"is_available": dish.is_available}
    dish.is_available = body.is_available
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="availability_toggled",
        before=before, after={"is_available": body.is_available},
    )
    await session.commit()
    await session.refresh(dish)
    await _refresh_grounding(session, restaurant.id)
    return dish


@router.patch("/dishes/{dish_id}/whatsapp", response_model=DishOut)
async def toggle_whatsapp(
    dish_id: int,
    body: WhatsappToggleIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Manager turns a dish's WhatsApp catalogue presence ON or OFF.

    OFF → unpublish it from the Meta catalogue (and drop the local mirror) so it is no
    longer linked or shown on WhatsApp. ON → republish so it shows again once Meta has
    processed it. Independent of availability and of the automatic review-gating."""
    from app.catalog.meta_client import _dish_retailer_id

    dish = await session.get(Dish, dish_id)
    if dish is None or dish.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dish not found")
    before = {"whatsapp_enabled": dish.whatsapp_enabled}
    dish.whatsapp_enabled = body.enabled
    rid = restaurant.id
    retailer_ids = {
        r for r in (
            (dish.catalog_retailer_id or "").strip(),
            _dish_retailer_id(dish.id, dish.dish_number),
        ) if r
    }
    await record_audit(
        session, actor="manager", restaurant_id=restaurant.id, entity="dish",
        entity_id=str(dish.id), action="whatsapp_toggled",
        before=before, after={"whatsapp_enabled": body.enabled},
    )
    await session.commit()
    await session.refresh(dish)
    # Turned OFF → remove from Meta now so it stops showing on WhatsApp. (Turned ON →
    # _refresh_grounding's auto-publish below pushes it back.)
    if not body.enabled:
        for retailer_id in retailer_ids:
            try:
                await unpublish_from_meta(session, restaurant_id=rid, retailer_id=retailer_id)
                await session.commit()
            except Exception:  # noqa: BLE001 — unpublish must never fail the toggle
                await session.rollback()
    await _refresh_grounding(session, rid)
    await session.refresh(dish)
    return dish


@router.post("/menus/{menu_id}/activate", response_model=MenuOut)
async def activate_menu(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    try:
        return await service.activate_menu(session, menu)
    except MenuIncompleteError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))


@router.post("/menus/{menu_id}/reextract", response_model=MenuWithDiffOut, status_code=200)
async def reextract_menu(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
    extractor: MenuExtractor = Depends(get_menu_extractor),
):
    menu = await _load_menu(menu_id, restaurant, session)
    try:
        new_menu, report = await service.reextract_menu(session, menu=menu, extractor=extractor)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc))
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"menu re-extraction failed: {exc}")
    out = MenuWithDiffOut.model_validate(new_menu)
    if report is not None:
        out.diff_vs_active = DiffOut(
            price_changes=[
                {**c, "old_price": str(c["old_price"]), "new_price": str(c["new_price"])}
                for c in report.price_changes
            ],
            added=[d.model_dump(mode="json") for d in report.added],
            removed=report.removed,
            conflicts=report.conflicts,
        )
    return out
