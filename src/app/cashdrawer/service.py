from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cashdrawer.models import CashDrawerEvent, CashDrawerSession


class DrawerAlreadyOpenError(Exception):
    pass


class DrawerNotFoundError(Exception):
    pass


async def get_current_session(session: AsyncSession, *, restaurant_id: int) -> CashDrawerSession | None:
    return await session.scalar(
        select(CashDrawerSession).where(
            CashDrawerSession.restaurant_id == restaurant_id,
            CashDrawerSession.status == "open",
        )
    )


async def open_session(
    session: AsyncSession, *, restaurant_id: int, opened_by: str, opening_float_aed: Decimal
) -> CashDrawerSession:
    existing = await get_current_session(session, restaurant_id=restaurant_id)
    if existing is not None:
        raise DrawerAlreadyOpenError(f"restaurant {restaurant_id} already has an open drawer session")
    row = CashDrawerSession(
        restaurant_id=restaurant_id, opened_by=opened_by, opened_at=datetime.now(timezone.utc),
        opening_float_aed=opening_float_aed, status="open",
    )
    session.add(row)
    await session.flush()
    return row


async def add_event(
    session: AsyncSession, *, session_id: int, restaurant_id: int, type: str,
    amount_aed: Decimal, reason: str | None, created_by: str,
) -> CashDrawerEvent:
    drawer = await session.get(CashDrawerSession, session_id)
    if drawer is None or drawer.restaurant_id != restaurant_id:
        raise DrawerNotFoundError(f"drawer session {session_id} not found")
    event = CashDrawerEvent(
        restaurant_id=restaurant_id, session_id=session_id, type=type,
        amount_aed=amount_aed, reason=reason, created_by=created_by,
    )
    session.add(event)
    await session.flush()
    return event


async def close_session(
    session: AsyncSession, *, session_id: int, restaurant_id: int, closed_by: str, closing_count_aed: Decimal,
) -> CashDrawerSession:
    drawer = await session.get(CashDrawerSession, session_id)
    if drawer is None or drawer.restaurant_id != restaurant_id:
        raise DrawerNotFoundError(f"drawer session {session_id} not found")

    events = (await session.scalars(
        select(CashDrawerEvent).where(CashDrawerEvent.session_id == session_id)
    )).all()
    cash_in = sum((e.amount_aed for e in events if e.type == "cash_in"), Decimal("0.00"))
    cash_out = sum((e.amount_aed for e in events if e.type == "cash_out"), Decimal("0.00"))
    expected = drawer.opening_float_aed + cash_in - cash_out

    drawer.closed_by = closed_by
    drawer.closed_at = datetime.now(timezone.utc)
    drawer.closing_count_aed = closing_count_aed
    drawer.variance_aed = closing_count_aed - expected
    drawer.status = "closed"
    await session.flush()
    return drawer
