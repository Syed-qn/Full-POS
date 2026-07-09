"""Scheduled / pre-order kitchen release."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.ordering.fsm import OrderStatus
from app.ordering.models import Order
from app.ordering.service import finalize_confirmation


async def release_due_scheduled_orders(
    session: AsyncSession,
    *,
    restaurant_id: int | None = None,
    now: datetime | None = None,
) -> list[Order]:
    """Finalize draft scheduled/pre-orders whose ``scheduled_for`` has arrived.

    Kitchen tickets + inventory deduction run via ``finalize_confirmation``.
    Idempotent: already-released or non-draft orders are skipped.
    """
    now = now or datetime.now(timezone.utc)
    # Compare as aware UTC so we match both naive and aware scheduled_for rows.
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    stmt = select(Order).where(
        Order.scheduled_for.is_not(None),
        Order.scheduled_released_at.is_(None),
        Order.status == OrderStatus.DRAFT,
    )
    if restaurant_id is not None:
        stmt = stmt.where(Order.restaurant_id == restaurant_id)

    candidates = list((await session.scalars(stmt)).all())
    released: list[Order] = []
    for order in candidates:
        if order.held_at is not None:
            continue
        sf = order.scheduled_for
        if sf is None:
            continue
        if sf.tzinfo is None:
            sf_aware = sf.replace(tzinfo=timezone.utc)
        else:
            sf_aware = sf.astimezone(timezone.utc)
        if sf_aware > now:
            continue
        await finalize_confirmation(session, order=order, actor="scheduler")
        order.scheduled_released_at = datetime.now(timezone.utc)
        await record_audit(
            session,
            restaurant_id=order.restaurant_id,
            actor="scheduler",
            entity="order",
            entity_id=str(order.id),
            action="scheduled_released",
            after={"scheduled_for": order.scheduled_for.isoformat() if order.scheduled_for else None},
        )
        released.append(order)
    await session.flush()
    return released
