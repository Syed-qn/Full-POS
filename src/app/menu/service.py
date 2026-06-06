
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.llm.port import DishDraft, MenuExtractor, UploadedFile
from app.menu.models import Dish, Menu, MenuFile
from app.menu.storage import FileBlobStore


def _get_store() -> FileBlobStore:
    from app.config import get_settings

    return FileBlobStore(base_dir=get_settings().upload_dir)


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


class MenuIncompleteError(Exception):
    pass


async def activate_menu(session: AsyncSession, menu: Menu) -> Menu:
    incomplete = [
        d for d in menu.dishes if d.dish_number is None or d.price_aed is None
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
