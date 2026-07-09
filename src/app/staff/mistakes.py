"""Staff mistake tracking."""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.staff.models import StaffMistake

MISTAKE_TYPES = frozenset(
    {"void", "wrong_item", "comp", "spill", "overcharge", "undercharge", "other"}
)


async def record_mistake(
    session: AsyncSession,
    *,
    restaurant_id: int,
    staff_id: int,
    mistake_type: str,
    order_id: int | None = None,
    amount_aed: Decimal = Decimal("0.00"),
    notes: str | None = None,
) -> StaffMistake:
    mt = (mistake_type or "other").strip().lower()
    if mt not in MISTAKE_TYPES:
        raise ValueError(f"invalid mistake_type; allowed: {sorted(MISTAKE_TYPES)}")
    row = StaffMistake(
        restaurant_id=restaurant_id,
        staff_id=staff_id,
        order_id=order_id,
        mistake_type=mt,
        amount_aed=amount_aed,
        notes=notes,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor=f"staff:{staff_id}",
        entity="staff_mistake",
        entity_id=str(row.id),
        action="mistake_recorded",
        after={
            "type": mt,
            "order_id": order_id,
            "amount_aed": str(amount_aed),
        },
    )
    return row


async def list_mistakes(
    session: AsyncSession,
    *,
    restaurant_id: int,
    staff_id: int | None = None,
    limit: int = 50,
) -> list[StaffMistake]:
    stmt = (
        select(StaffMistake)
        .where(StaffMistake.restaurant_id == restaurant_id)
        .order_by(StaffMistake.created_at.desc())
        .limit(min(max(limit, 1), 100))
    )
    if staff_id is not None:
        stmt = stmt.where(StaffMistake.staff_id == staff_id)
    return list((await session.scalars(stmt)).all())
