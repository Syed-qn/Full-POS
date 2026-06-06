from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.llm.port import DishDraft, MenuExtractor, UploadedFile
from app.menu.models import Dish, Menu


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
