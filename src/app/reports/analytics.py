from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditLog
from app.inventory.models import DishIngredient
from app.ordering.models import Order, OrderItem


def _day_window(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    return datetime.combine(start_date, time.min), datetime.combine(end_date, time.max)


async def item_performance(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
        )
    )).all()
    order_ids = [o.id for o in orders]
    if not order_ids:
        return []
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    )).all()

    by_dish: dict[str, dict] = {}
    for item in items:
        row = by_dish.setdefault(item.dish_name, {"dish_name": item.dish_name, "order_count": 0, "revenue_aed": Decimal("0.00")})
        row["order_count"] += item.qty
        row["revenue_aed"] += item.price_aed * item.qty

    return sorted(by_dish.values(), key=lambda r: r["revenue_aed"], reverse=True)


async def inventory_usage(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    from app.inventory.models import Ingredient

    day_start, day_end = _day_window(start_date, end_date)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.created_at >= day_start, Order.created_at <= day_end,
        )
    )).all()
    order_ids = [o.id for o in orders]
    if not order_ids:
        return []
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id.in_(order_ids))
    )).all()
    qty_by_dish: dict[int, int] = defaultdict(int)
    for item in items:
        qty_by_dish[item.dish_id] += item.qty

    recipes = (await session.scalars(
        select(DishIngredient).where(DishIngredient.dish_id.in_(qty_by_dish.keys()))
    )).all()
    used: dict[int, Decimal] = defaultdict(lambda: Decimal("0.000"))
    for recipe in recipes:
        used[recipe.ingredient_id] += recipe.quantity_per_dish * qty_by_dish[recipe.dish_id]

    ingredients = (await session.scalars(
        select(Ingredient).where(Ingredient.id.in_(used.keys()))
    )).all()
    by_id = {ing.id: ing for ing in ingredients}
    return [
        {"ingredient_id": iid, "ingredient_name": by_id[iid].name, "quantity_used": qty}
        for iid, qty in used.items() if iid in by_id
    ]


async def table_turn_time(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> list[dict]:
    day_start, day_end = _day_window(start_date, end_date)
    rows = (await session.scalars(
        select(AuditLog).where(
            AuditLog.restaurant_id == restaurant_id, AuditLog.entity == "table",
            AuditLog.created_at >= day_start, AuditLog.created_at <= day_end,
        ).order_by(AuditLog.created_at)
    )).all()

    by_table: dict[str, list[AuditLog]] = defaultdict(list)
    for row in rows:
        by_table[row.entity_id].append(row)

    results = []
    for table_id, events in by_table.items():
        seated_at: datetime | None = None
        for event in events:
            after_status = (event.after or {}).get("status")
            if after_status == "seated":
                seated_at = event.created_at
            elif after_status == "available" and seated_at is not None:
                minutes = (event.created_at - seated_at).total_seconds() / 60.0
                results.append({"table_id": int(table_id), "turn_minutes": round(minutes, 2)})
                seated_at = None
    return results


async def labor_hours(session: AsyncSession, *, restaurant_id: int, target_date: date) -> list[dict]:
    from app.staff.models import StaffMember
    from app.staff.service import compute_hours

    staff_rows = (await session.scalars(
        select(StaffMember).where(StaffMember.restaurant_id == restaurant_id)
    )).all()
    results = []
    for staff in staff_rows:
        hours = await compute_hours(
            session, staff_id=staff.id, restaurant_id=restaurant_id, target_date=target_date
        )
        if hours > 0:
            results.append({"staff_id": staff.id, "name": staff.name, "hours": round(hours, 2)})
    return results
