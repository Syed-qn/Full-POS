# src/app/audit/backup_status.py
"""Backup-readiness self-check.

NOT a real backup integration (this repo has none). This is the diagnostic a
manager/admin would want before trusting that backups are working: a live
row-count sanity signal that the tenant's core data ("does this restaurant's
data look intact right now") is present and the DB is queryable.
"""

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.menu.models import Dish
from app.ordering.models import Customer, Order


async def backup_readiness(session: AsyncSession, *, restaurant_id: int) -> dict:
    orders_count = await session.scalar(
        select(func.count()).select_from(Order).where(Order.restaurant_id == restaurant_id)
    )
    customers_count = await session.scalar(
        select(func.count()).select_from(Customer).where(Customer.restaurant_id == restaurant_id)
    )
    dishes_count = await session.scalar(
        select(func.count()).select_from(Dish).where(Dish.restaurant_id == restaurant_id)
    )

    return {
        "orders_count": int(orders_count or 0),
        "customers_count": int(customers_count or 0),
        "dishes_count": int(dishes_count or 0),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
