"""Dedicated Category entity — replaces free-text Dish.category as the source of
truth for category management, while keeping Dish.category (denormalized name)
in sync so every existing reader (LLM menu import, KDS station routing via
CategoryStationDefault, frontend client-side grouping) keeps working unchanged.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.menu.models import Category, Dish


async def create_category(
    session: AsyncSession,
    *,
    restaurant_id: int,
    name: str,
    sort_order: int = 0,
    parent_id: int | None = None,
) -> Category:
    name = name.strip()
    existing = await session.scalar(
        select(Category).where(Category.restaurant_id == restaurant_id, Category.name == name)
    )
    if existing is not None:
        raise ValueError(f"category '{name}' already exists")
    if parent_id is not None:
        parent = await session.get(Category, parent_id)
        if parent is None or parent.restaurant_id != restaurant_id:
            raise ValueError("parent category not found")
    row = Category(
        restaurant_id=restaurant_id, name=name, sort_order=sort_order, parent_id=parent_id
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="category",
        entity_id=str(row.id), action="created",
        before=None, after={"name": name, "parent_id": parent_id},
    )
    return row


async def list_categories(session: AsyncSession, *, restaurant_id: int) -> list[Category]:
    return list((await session.scalars(
        select(Category).where(Category.restaurant_id == restaurant_id).order_by(Category.sort_order, Category.id)
    )).all())


async def rename_category(
    session: AsyncSession, *, restaurant_id: int, category_id: int, name: str
) -> Category:
    cat = await session.get(Category, category_id)
    if cat is None or cat.restaurant_id != restaurant_id:
        raise ValueError("category not found")
    before = cat.name
    cat.name = name.strip()
    # Denormalized name lives on every dish currently assigned to this category.
    dishes = (await session.scalars(
        select(Dish).where(Dish.category_id == category_id, Dish.restaurant_id == restaurant_id)
    )).all()
    for d in dishes:
        d.category = cat.name
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="category",
        entity_id=str(cat.id), action="renamed", before={"name": before}, after={"name": cat.name},
    )
    await session.flush()
    return cat


async def delete_category(session: AsyncSession, *, restaurant_id: int, category_id: int) -> None:
    cat = await session.get(Category, category_id)
    if cat is None or cat.restaurant_id != restaurant_id:
        raise ValueError("category not found")
    in_use = await session.scalar(
        select(Dish.id).where(Dish.category_id == category_id, Dish.restaurant_id == restaurant_id).limit(1)
    )
    if in_use is not None:
        raise ValueError("cannot delete a category that dishes still reference")
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="category",
        entity_id=str(cat.id), action="deleted", before={"name": cat.name}, after=None,
    )
    await session.delete(cat)
    await session.flush()


async def assign_dish_category(
    session: AsyncSession, *, restaurant_id: int, dish_id: int, category_id: int
) -> Dish:
    dish = await session.get(Dish, dish_id)
    if dish is None or dish.restaurant_id != restaurant_id:
        raise ValueError("dish not found")
    cat = await session.get(Category, category_id)
    if cat is None or cat.restaurant_id != restaurant_id:
        raise ValueError("category not found")
    before = dish.category
    dish.category_id = cat.id
    dish.category = cat.name
    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id, entity="dish",
        entity_id=str(dish.id), action="category_assigned",
        before={"category": before}, after={"category": cat.name},
    )
    await session.flush()
    return dish
