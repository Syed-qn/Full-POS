import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.llm.port import DishDraft, MenuExtractor, UploadedFile
from app.menu.models import Dish, Menu, MenuFile
from app.menu.storage import FileBlobStore
from app.ordering.matching import normalize_name

# Dish photo upload limits (Meta catalogue images): JPG/PNG, 5 MB cap.
DISH_IMAGE_MIMES = {"image/jpeg", "image/png"}
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
    from app.marketing.models import MarketingMedia

    ext = "png" if content_type == "image/png" else "jpg"
    rel = f"dishes/{restaurant_id}/{uuid.uuid4().hex}.{ext}"
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
    for d in drafts:
        session.add(
            Dish(
                menu_id=menu.id,
                restaurant_id=restaurant_id,
                dish_number=d.dish_number,
                name=d.name,
                name_normalized=normalize_name(d.name),
                price_aed=d.price_aed,
                category=d.category,
                description=d.description,
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
    previous = await get_active_menu(session, menu.restaurant_id)
    if previous and previous.id != menu.id:
        previous.status = "superseded"
    menu.status = "active"
    await record_audit(
        session, actor="manager", restaurant_id=menu.restaurant_id, entity="menu",
        entity_id=str(menu.id), action="activated",
        after={"version": menu.version},
    )
    await session.commit()
    await session.refresh(menu)

    # Refresh OKF grounding so the bot answers from the NEW menu, not stale dish
    # docs. Best-effort — a grounding-refresh hiccup must never fail activation.
    try:
        from app.okf.producer import refresh_menu_and_policy

        await refresh_menu_and_policy(session, restaurant_id=menu.restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()

    # Auto-publish to the Meta catalogue so every available, priced dish shows as a
    # WhatsApp catalogue card — the manager keeps ONE menu and never clicks "Sync".
    # Best-effort: no catalog_id / Meta down must never fail activation.
    try:
        from app.catalog.sync_service import auto_publish_to_meta

        await auto_publish_to_meta(session, restaurant_id=menu.restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001
        await session.rollback()
    return menu


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
