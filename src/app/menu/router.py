import io
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
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
    BulkCsvImportOut,
    BulkPriceUpdateIn,
    BulkPriceUpdateOut,
    DiffOut,
    DishIn,
    DishOut,
    DishPatch,
    MenuOut,
    MenuWithDiffOut,
    SellRuleIn,
    SellRuleOut,
    WhatsappToggleIn,
    serialize_variants,
)
from app.menu.service import (
    MenuApprovalError,
    MenuIncompleteError,
    approve_menu,
    submit_menu_for_approval,
)
from app.menu.unified import UnifiedMenuOut, build_unified_menu
from app.catalog.sync_service import schedule_auto_publish, unpublish_from_meta
from app.okf.producer import refresh_okf_for_restaurant


async def _refresh_grounding(session: AsyncSession, restaurant_id: int) -> None:
    """Run after a dish mutation on these inline endpoints (which bypass activate_menu):
      1. rebuild OKF menu/policy docs INLINE so the bot grounds on the live menu at once;
      2. publish the menu to the Meta catalogue in the BACKGROUND so a slow Meta round-trip
         never makes the manager's save hang (the save returns as soon as the DB commit +
         grounding are done).
    Both are best-effort — neither may fail the manager's edit."""
    try:
        await refresh_okf_for_restaurant(session, restaurant_id=restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
    schedule_auto_publish(restaurant_id)

router = APIRouter(prefix="/api/v1", tags=["menu"])

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def _menu_out(menu: Menu) -> MenuOut:
    """Serialize a menu for the manager dashboard, hiding archived (soft-deleted) dishes."""
    out = MenuOut.model_validate(menu)
    out.dishes = [d for d in out.dishes if d.meta_status != "archived"]
    return out


async def _fill_catalog_images(
    session: AsyncSession, restaurant_id: int, out: MenuOut
) -> None:
    """For a dish that has no own ``image_url`` but is linked to a Meta catalogue product,
    surface that product's image so the edit modal prefills the existing photo (dishes
    auto-created/linked from a Meta sync keep the image on the catalogue row, not the
    dish row)."""
    from app.catalog.models import CatalogProduct

    rids = [
        d.catalog_retailer_id
        for d in out.dishes
        if not (d.image_url or "").strip() and d.catalog_retailer_id
    ]
    if not rids:
        return
    rows = (
        await session.scalars(
            select(CatalogProduct).where(
                CatalogProduct.restaurant_id == restaurant_id,
                CatalogProduct.retailer_id.in_(rids),
            )
        )
    ).all()
    by_rid = {r.retailer_id: r.image_url for r in rows if (r.image_url or "").strip()}
    for d in out.dishes:
        if not (d.image_url or "").strip() and d.catalog_retailer_id in by_rid:
            d.image_url = by_rid[d.catalog_retailer_id]


async def _load_menu(
    menu_id: int,
    restaurant: Restaurant,
    session: AsyncSession,
) -> Menu:
    menu = await session.get(Menu, menu_id)
    if menu is None or menu.restaurant_id != restaurant.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "menu not found")
    return menu


@router.post("/menus/blank", response_model=MenuOut, status_code=201)
async def create_blank_menu(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Return the active menu, creating an empty one if none exists — so a manager can
    start adding dishes without uploading a file first."""
    menu = await service.ensure_active_menu(session, restaurant.id)
    await session.commit()
    await session.refresh(menu)
    return _menu_out(menu)


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


@router.get("/menu/dishes", response_model=list[DishOut])
async def list_dishes(
    updated_since: datetime | None = Query(default=None),
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[Dish]:
    """Flat dish list for the active menu — used by the desktop client's pull sync
    (Task 8). ``updated_since`` filters to rows changed after that cursor timestamp;
    omitting it returns every non-archived dish on the active menu."""
    return await service.list_dishes(session, restaurant.id, updated_since=updated_since)


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
    out = _menu_out(menu)
    await _fill_catalog_images(session, restaurant.id, out)
    return out


@router.get("/menus/{menu_id}", response_model=MenuOut)
async def get_menu(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    menu = await _load_menu(menu_id, restaurant, session)
    out = _menu_out(menu)
    await _fill_catalog_images(session, restaurant.id, out)
    return out


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
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "Dish photo must be an image (JPG, PNG, or WebP)",
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
    if data.get("nutrition") is None:
        data["nutrition"] = {}
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
    # A dish removed from a DRAFT menu (the post-upload review dialog) was never pushed to
    # Meta and isn't grounding the live bot, so skip the slow Meta unpublish + grounding
    # refresh and just drop the row — the delete stays instant. Only touch Meta/grounding
    # when the dish could actually be live: the menu is active, or the dish carries a link.
    menu_is_live = menu.status == "active"
    was_linked = bool((dish.catalog_retailer_id or "").strip())
    touch_meta = menu_is_live or was_linked
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
    } if touch_meta else set()
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
        dish.meta_status = "archived"
        await record_audit(
            session, actor="manager", restaurant_id=restaurant.id, entity="dish",
            entity_id=str(dish.id), action="deactivated",
            before={"dish_number": dish.dish_number, "name": dish.name},
            after={"reason": "deleted in OPS; has order history → archived"},
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
    # Skipped entirely for a draft-menu dish that was never published (fast path).
    for retailer_id in retailer_ids:
        try:
            await unpublish_from_meta(session, restaurant_id=rid, retailer_id=retailer_id)
            await session.commit()
        except Exception:  # noqa: BLE001 — unpublish must never fail the delete
            await session.rollback()
    # Bot grounding only matters for the live menu; a draft edit never affects it.
    if menu_is_live:
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


@router.post("/menus/{menu_id}/submit-for-approval", response_model=MenuOut)
async def submit_menu_for_approval_endpoint(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        menu = await submit_menu_for_approval(session, restaurant_id=restaurant.id, menu_id=menu_id)
        await session.commit()
        await session.refresh(menu)
        return menu
    except MenuApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/menus/{menu_id}/approve", response_model=MenuOut)
async def approve_menu_endpoint(
    menu_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        menu = await approve_menu(
            session, restaurant_id=restaurant.id, menu_id=menu_id, approved_by=f"mgr:{restaurant.id}"
        )
        await session.commit()
        await session.refresh(menu)
        return menu
    except MenuApprovalError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except MenuIncompleteError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


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


@router.post("/menus/{menu_id}/bulk-price-update", response_model=BulkPriceUpdateOut)
async def bulk_price_update(
    menu_id: int,
    body: BulkPriceUpdateIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Bulk set absolute prices or apply a percent delta to many dishes."""
    from decimal import Decimal

    menu = await _load_menu(menu_id, restaurant, session)
    if not body.dish_ids:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "dish_ids required")
    if body.price_aed is None and body.percent_delta is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "price_aed or percent_delta required"
        )
    dishes = (
        await session.scalars(
            select(Dish).where(
                Dish.menu_id == menu.id,
                Dish.restaurant_id == restaurant.id,
                Dish.id.in_(body.dish_ids),
            )
        )
    ).all()
    updated_ids: list[int] = []
    for dish in dishes:
        before = str(dish.price_aed)
        if body.price_aed is not None:
            dish.price_aed = body.price_aed
        elif body.percent_delta is not None and dish.price_aed is not None:
            factor = Decimal("1") + (body.percent_delta / Decimal("100"))
            dish.price_aed = (dish.price_aed * factor).quantize(Decimal("0.01"))
        updated_ids.append(dish.id)
        await record_audit(
            session,
            actor="manager",
            restaurant_id=restaurant.id,
            entity="dish",
            entity_id=str(dish.id),
            action="bulk_price_update",
            before={"price_aed": before},
            after={"price_aed": str(dish.price_aed)},
        )
    await session.commit()
    return BulkPriceUpdateOut(updated=len(updated_ids), dish_ids=updated_ids)


@router.post("/menus/{menu_id}/bulk-csv-import", response_model=BulkCsvImportOut)
async def bulk_csv_import(
    menu_id: int,
    file: UploadFile,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """CSV bulk menu import.

    Columns (header row required): dish_number,name,price_aed,category,description,
    name_ar,allergens (pipe-separated),channels_allowed (pipe-separated),stock_remaining,
    brand_menu_code,available_from,available_until
    """
    import csv
    from decimal import Decimal, InvalidOperation
    from datetime import date as date_cls

    menu = await _load_menu(menu_id, restaurant, session)
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    created = 0
    updated = 0
    errors: list[str] = []
    for i, row in enumerate(reader, start=2):
        try:
            num = int(str(row.get("dish_number") or "").strip())
            name = (row.get("name") or "").strip()
            if not name:
                raise ValueError("name required")
            price = Decimal(str(row.get("price_aed") or "0").strip())
            dish = await session.scalar(
                select(Dish).where(Dish.menu_id == menu.id, Dish.dish_number == num)
            )
            allergens = [
                a.strip() for a in (row.get("allergens") or "").split("|") if a.strip()
            ]
            channels = [
                c.strip()
                for c in (row.get("channels_allowed") or "").split("|")
                if c.strip()
            ]
            stock_raw = (row.get("stock_remaining") or "").strip()
            stock = int(stock_raw) if stock_raw else None
            af = (row.get("available_from") or "").strip() or None
            au = (row.get("available_until") or "").strip() or None
            available_from = date_cls.fromisoformat(af) if af else None
            available_until = date_cls.fromisoformat(au) if au else None
            if dish is None:
                dish = Dish(
                    menu_id=menu.id,
                    restaurant_id=restaurant.id,
                    dish_number=num,
                    name=name,
                    price_aed=price,
                    category=(row.get("category") or None),
                    description=(row.get("description") or None),
                    name_ar=(row.get("name_ar") or None),
                    allergens=allergens,
                    channels_allowed=channels,
                    stock_remaining=stock,
                    brand_menu_code=(row.get("brand_menu_code") or None),
                    available_from=available_from,
                    available_until=available_until,
                    name_normalized=normalize_name(name),
                )
                session.add(dish)
                created += 1
            else:
                dish.name = name
                dish.price_aed = price
                dish.category = row.get("category") or dish.category
                dish.description = row.get("description") or dish.description
                dish.name_ar = row.get("name_ar") or dish.name_ar
                if allergens:
                    dish.allergens = allergens
                if channels:
                    dish.channels_allowed = channels
                if stock is not None:
                    dish.stock_remaining = stock
                if row.get("brand_menu_code"):
                    dish.brand_menu_code = row["brand_menu_code"]
                dish.available_from = available_from
                dish.available_until = available_until
                dish.name_normalized = normalize_name(name)
                updated += 1
        except (ValueError, InvalidOperation, KeyError) as exc:
            errors.append(f"row {i}: {exc}")
    await session.commit()
    return BulkCsvImportOut(created=created, updated=updated, errors=errors)


@router.post("/menus/sell-rules", response_model=SellRuleOut, status_code=201)
async def create_sell_rule(
    body: SellRuleIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    from app.menu.models import MenuSellRule

    if body.rule_kind not in ("upsell", "cross_sell"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "rule_kind must be upsell|cross_sell")
    if not body.trigger_dish_id and not body.trigger_category:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "trigger_dish_id or trigger_category required",
        )
    rule = MenuSellRule(
        restaurant_id=restaurant.id,
        rule_kind=body.rule_kind,
        trigger_dish_id=body.trigger_dish_id,
        trigger_category=body.trigger_category,
        suggest_dish_id=body.suggest_dish_id,
        message=body.message,
        sort_order=body.sort_order,
        is_active=body.is_active,
    )
    session.add(rule)
    await session.commit()
    await session.refresh(rule)
    return rule


@router.get("/menus/sell-rules", response_model=list[SellRuleOut])
async def list_sell_rules(
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    from app.menu.models import MenuSellRule

    rows = await session.scalars(
        select(MenuSellRule)
        .where(MenuSellRule.restaurant_id == restaurant.id)
        .order_by(MenuSellRule.sort_order, MenuSellRule.id)
    )
    return list(rows)
