import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.llm.port import DishDraft, MenuExtractor, UploadedFile
from app.menu.models import Dish, Menu, MenuFile
from app.menu.storage import FileBlobStore
from app.ordering.matching import normalize_name

# Dish photo upload: accept phone photos up to 5 MB; stored compressed for catalog cards.
DISH_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
MAX_DISH_IMAGE_BYTES = 5 * 1024 * 1024


def _get_store() -> FileBlobStore:
    from app.config import get_settings

    return FileBlobStore(base_dir=get_settings().upload_dir)


async def store_dish_image(
    session: AsyncSession,
    *,
    restaurant_id: int,
    content: bytes,
    content_type: str,
) -> str:
    """Persist a dish photo in Postgres (``marketing_media``) and return its public
    ``/media/<path>`` URL. Stored in the DB (not local disk) so the image survives
    redeploys on ephemeral-disk hosts and is fetchable by Meta as the product
    ``image_link``. Caller commits."""
    from app.config import get_settings
    from app.menu.image_catalog import compress_for_catalog_image
    from app.marketing.models import MarketingMedia

    try:
        content, content_type = compress_for_catalog_image(content)
    except Exception:
        pass  # tiny/invalid — store as-is; push falls back to placeholder
    rel = f"dishes/{restaurant_id}/{uuid.uuid4().hex}.jpg"
    session.add(
        MarketingMedia(
            restaurant_id=restaurant_id,
            path=rel,
            content_type=content_type or "image/jpeg",
            data=content,
        )
    )
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/media/{rel}"


async def ensure_stored_dish_image_compressed(
    session: AsyncSession, *, image_url: str | None
) -> bool:
    """Re-compress stored dish photos that are too large for WhatsApp catalog cards."""
    from sqlalchemy import select

    from app.menu.image_catalog import (
        CATALOG_IMAGE_MAX_BYTES,
        compress_for_catalog_image,
        media_path_from_url,
    )
    from app.marketing.models import MarketingMedia

    path = media_path_from_url(image_url)
    if not path or not path.startswith("dishes/"):
        return False
    row = await session.scalar(
        select(MarketingMedia).where(MarketingMedia.path == path).limit(1)
    )
    if row is None or len(row.data) <= CATALOG_IMAGE_MAX_BYTES:
        return False
    try:
        row.data, row.content_type = compress_for_catalog_image(row.data)
    except Exception:
        return False
    return True


async def upload_with_diff(
    session: AsyncSession,
    *,
    restaurant_id: int,
    files: list[UploadedFile],
    extractor: MenuExtractor,
) -> "tuple[Menu, object | None]":
    """Create menu from upload and compute diff vs active menu.

    Returns (menu, DiffReport-or-None). DiffReport is None when there is no
    prior active menu to compare against.
    """
    from app.menu.diff import DiffReport, diff_menus

    menu = await create_menu_from_upload(
        session, restaurant_id=restaurant_id, files=files, extractor=extractor
    )
    active = await get_active_menu(session, restaurant_id)
    if active is None or active.id == menu.id:
        return menu, None
    report: DiffReport = diff_menus(
        active.dishes,
        [
            DishDraft(
                dish_number=d.dish_number,
                name=d.name,
                price_aed=d.price_aed,
                category=d.category,
                description=d.description,
            )
            for d in menu.dishes
        ],
    )
    return menu, report


async def next_version(session: AsyncSession, restaurant_id: int) -> int:
    current = await session.scalar(
        select(func.max(Menu.version)).where(Menu.restaurant_id == restaurant_id)
    )
    return (current or 0) + 1


async def create_menu_from_upload(
    session: AsyncSession,
    *,
    restaurant_id: int,
    files: list[UploadedFile],
    extractor: MenuExtractor,
) -> Menu:
    drafts: list[DishDraft] = await extractor.extract_menu(files)
    menu = Menu(
        restaurant_id=restaurant_id,
        version=await next_version(session, restaurant_id),
        status="pending_confirmation",
        source_files=[{"filename": f.filename, "mime": f.mime} for f in files],
    )
    session.add(menu)
    await session.flush()
    store = _get_store()
    for f in files:
        sha = store.put(
            restaurant_id=restaurant_id,
            data=f.content,
            content_type=f.mime,
        )
        session.add(
            MenuFile(
                restaurant_id=restaurant_id,
                menu_id=menu.id,
                sha256=sha,
                content_type=f.mime,
                size_bytes=len(f.content),
                original_filename=f.filename,
            )
        )
    await session.flush()
    # Auto-assign dish numbers so extracted dishes are always activatable (spec: dish
    # number is mandatory). Keep any number Claude read off the menu; fill every gap/null
    # with the next free sequential number — mirrors how "+ Add dish" assigns max+1 and
    # hides the field in the UI, so the manager never has to type numbers by hand.
    # Seed the "used" set with this restaurant's EXISTING dish numbers (other menu versions)
    # too, so an auto-assigned number never collides with an old dish.
    existing_numbers = set(
        (
            await session.scalars(
                select(Dish.dish_number).where(
                    Dish.restaurant_id == restaurant_id,
                    Dish.dish_number.is_not(None),
                )
            )
        ).all()
    )
    used_numbers = existing_numbers | {
        d.dish_number for d in drafts if d.dish_number is not None
    }
    _counter = 0
    for d in drafts:
        if d.dish_number is not None:
            number = d.dish_number
        else:
            _counter += 1
            while _counter in used_numbers:
                _counter += 1
            used_numbers.add(_counter)
            number = _counter
        session.add(
            Dish(
                menu_id=menu.id,
                restaurant_id=restaurant_id,
                dish_number=number,
                name=d.name,
                name_normalized=normalize_name(d.name),
                price_aed=d.price_aed,
                category=d.category,
                description=d.description,
                variants=[
                    {"name": v.name, "price_aed": str(v.price_aed), "dish_number": None}
                    for v in d.variants
                ],
            )
        )
    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="menu",
        entity_id=str(menu.id),
        action="uploaded",
        after={"version": menu.version, "dish_count": len(drafts)},
    )
    await session.commit()
    await session.refresh(menu)
    return menu


async def get_active_menu(session: AsyncSession, restaurant_id: int) -> Menu | None:
    return await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )


async def list_active_dishes_catalog(
    session: AsyncSession,
    *,
    restaurant_id: int,
    limit: int = 200,
) -> list[dict[str, int | str]]:
    """Read-only dish list for marketing segment compile (id + name)."""
    menu = await get_active_menu(session, restaurant_id)
    if menu is None:
        return []
    rows = (
        await session.scalars(
            select(Dish)
            .where(Dish.menu_id == menu.id, Dish.is_available.is_(True))
            .order_by(Dish.dish_number)
            .limit(limit)
        )
    ).all()
    return [{"id": d.id, "name": d.name} for d in rows]


async def ensure_active_menu(session: AsyncSession, restaurant_id: int) -> Menu:
    """Return the active menu, creating an empty one if the restaurant has none.

    Lets a manager start a menu by adding dishes directly (no upload required) — the
    "+ Add dish" button on an empty restaurant calls this to have something to add to.
    """
    existing = await get_active_menu(session, restaurant_id)
    if existing is not None:
        return existing
    menu = Menu(
        restaurant_id=restaurant_id,
        version=await next_version(session, restaurant_id),
        status="active",
        source_files=[],
    )
    session.add(menu)
    await session.flush()
    return menu


class MenuIncompleteError(Exception):
    pass


def _variants_incomplete(dish: Dish) -> bool:
    """True if any serving-size variant on the dish lacks a name or a positive price.

    Mirrors the base "dish needs number and price" rule (spec §): a variant without a
    price would let an order be placed with no resolvable amount, so it blocks activation.
    """
    from decimal import Decimal, InvalidOperation

    for v in (dish.variants or []):
        if not (v.get("name") or "").strip():
            return True
        raw = v.get("price_aed")
        if raw in (None, ""):
            return True
        try:
            if Decimal(str(raw)) <= 0:
                return True
        except (InvalidOperation, ValueError):
            return True
    return False


async def activate_menu(session: AsyncSession, menu: Menu) -> Menu:
    incomplete = [
        d
        for d in menu.dishes
        if d.dish_number is None or d.price_aed is None or _variants_incomplete(d)
    ]
    if incomplete:
        names = ", ".join(d.name for d in incomplete[:5])
        raise MenuIncompleteError(
            f"incomplete dishes (need number and price): {names}"
        )
    active = await get_active_menu(session, menu.restaurant_id)
    if active is None or active.id == menu.id:
        # First/only menu — this upload becomes the active menu.
        menu.status = "active"
        target = menu
        await record_audit(
            session, actor="manager", restaurant_id=menu.restaurant_id, entity="menu",
            entity_id=str(menu.id), action="activated",
            after={"version": menu.version},
        )
    else:
        # APPEND (bulk add): move this upload's dishes INTO the existing active menu rather
        # than replacing it — uploading N dishes grows the menu by N, exactly like "+ Add
        # dish" grows it by one. Renumber a dish only where its number would collide with an
        # existing active dish. Re-parent by moving between the ORM collections (not a raw
        # menu_id flip) so the delete-orphan cascade never deletes the moved dish.
        existing_nums = {d.dish_number for d in active.dishes if d.dish_number is not None}
        counter = max(existing_nums, default=0)
        moved = 0
        for d in list(menu.dishes):
            num = d.dish_number
            if num is None or num in existing_nums:
                counter += 1
                while counter in existing_nums:
                    counter += 1
                num = counter
            existing_nums.add(num)
            d.dish_number = num
            menu.dishes.remove(d)
            active.dishes.append(d)
            moved += 1
        menu.status = "superseded"  # the now-empty upload menu
        target = active
        await record_audit(
            session, actor="manager", restaurant_id=menu.restaurant_id, entity="menu",
            entity_id=str(active.id), action="appended",
            after={"added": moved, "into_version": active.version},
        )
    await session.commit()
    await session.refresh(target)

    # Refresh OKF grounding so the bot answers from the current menu, not stale dish
    # docs. Best-effort — a grounding-refresh hiccup must never fail activation.
    try:
        from app.okf.producer import refresh_menu_and_policy

        await refresh_menu_and_policy(session, restaurant_id=target.restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()

    # Auto-publish to the Meta catalogue so every available, priced dish shows as a
    # WhatsApp catalogue card — the manager keeps ONE menu and never clicks "Sync".
    # Runs in the BACKGROUND (own session) so a slow Meta push never makes "Confirm &
    # Activate" hang — the menu is already active + committed above. Best-effort: no
    # catalog_id / Meta down must never fail activation, and it re-attempts on any later
    # dish mutation.
    from app.catalog.sync_service import schedule_auto_publish

    schedule_auto_publish(target.restaurant_id)
    return target


async def fold_history_into_active_menu(
    session: AsyncSession, *, restaurant_id: int
) -> int:
    """Reconcile: move dishes that live in NON-active menus (old uploads that were
    superseded before the bulk-add change) INTO the active menu, so the OPS UI shows
    everything that's still live on WhatsApp / known to the bot. No deletes.

    Dedupes by catalog link (``catalog_retailer_id``) and normalized name — first
    occurrence wins, later duplicates are left where they are — and renumbers to avoid
    colliding with an existing active dish. Uses Core UPDATEs (not an ORM re-parent) to
    move rows in bulk without tripping the ``dishes`` delete-orphan cascade. Idempotent:
    a second run folds nothing new. Returns the number of dishes folded in. Caller's
    session is committed here.
    """
    active = await ensure_active_menu(session, restaurant_id)
    active_names = {d.name_normalized for d in active.dishes if d.name_normalized}
    active_rids = {
        (d.catalog_retailer_id or "").strip()
        for d in active.dishes
        if (d.catalog_retailer_id or "").strip()
    }
    active_nums = {d.dish_number for d in active.dishes if d.dish_number is not None}
    counter = max(active_nums, default=0)

    rows = (
        await session.execute(
            select(
                Dish.id, Dish.dish_number, Dish.name_normalized, Dish.catalog_retailer_id
            )
            .join(Menu, Dish.menu_id == Menu.id)
            .where(
                Dish.restaurant_id == restaurant_id,
                # Only old REPLACED menus — never a pending_confirmation draft the manager
                # is still reviewing (that would pull unconfirmed dishes live early) nor the
                # active menu itself.
                Menu.status == "superseded",
                Menu.id != active.id,
                Dish.meta_status != "archived",
            )
            .order_by(Dish.id)
        )
    ).all()

    folded = 0
    for did, dnum, dname, drid in rows:
        rid = (drid or "").strip()
        if (rid and rid in active_rids) or (dname and dname in active_names):
            continue  # already represented in the active menu — skip the duplicate
        num = dnum
        if num is None or num in active_nums:
            counter += 1
            while counter in active_nums:
                counter += 1
            num = counter
        active_nums.add(num)
        if dname:
            active_names.add(dname)
        if rid:
            active_rids.add(rid)
        await session.execute(
            update(Dish).where(Dish.id == did).values(menu_id=active.id, dish_number=num)
        )
        folded += 1

    if folded:
        await record_audit(
            session, actor="manager", restaurant_id=restaurant_id, entity="menu",
            entity_id=str(active.id), action="reconciled",
            after={"folded": folded},
        )
        # The active menu's cached ``dishes`` collection predates the Core UPDATEs above;
        # expire just that menu so the caller re-reads the folded-in dishes (an async
        # relationship reload inside the request greenlet, not a global expire).
        session.expire(active, ["dishes"])
    await session.commit()
    return folded


async def reextract_menu(
    session: AsyncSession,
    *,
    menu: Menu,
    extractor: MenuExtractor,
) -> "tuple[Menu, object | None]":
    """Re-run extraction on stored file bytes and return a new draft + diff."""
    store = _get_store()
    menu_files = (
        await session.scalars(
            select(MenuFile).where(
                MenuFile.menu_id == menu.id,
                MenuFile.restaurant_id == menu.restaurant_id,
            )
        )
    ).all()
    if not menu_files:
        raise ValueError("no stored files for this menu — re-upload required")
    reupload = [
        UploadedFile(
            filename=mf.original_filename or "file",
            content=store.get(restaurant_id=mf.restaurant_id, digest=mf.sha256) or b"",
            mime=mf.content_type,
        )
        for mf in menu_files
    ]
    new_menu, report = await upload_with_diff(
        session,
        restaurant_id=menu.restaurant_id,
        files=reupload,
        extractor=extractor,
    )
    return new_menu, report
