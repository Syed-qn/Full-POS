from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ordering.models import Order
from app.tables.models import DiningTable

_TRANSITIONS: dict[str, set[str]] = {
    "available": {"seated"},
    "seated": {"ordered", "available"},
    "ordered": {"needs_bill", "available"},
    "needs_bill": {"cleaning"},
    "cleaning": {"available"},
}


class TableNotFoundError(Exception):
    pass


class InvalidTableTransitionError(Exception):
    pass


class DuplicateTableLabelError(Exception):
    """Another live table on this floor already carries that label."""


class TableInUseError(Exception):
    """The table still has an open tab — it cannot be removed mid-service."""


async def _owned_table(
    session: AsyncSession, *, restaurant_id: int, table_id: int
) -> DiningTable:
    table = await session.get(DiningTable, table_id)
    if table is None or table.restaurant_id != restaurant_id or table.archived_at is not None:
        raise TableNotFoundError(f"table {table_id} not found")
    return table


async def assert_label_free(
    session: AsyncSession, *, restaurant_id: int, label: str, exclude_id: int | None = None
) -> None:
    """Labels are how staff call a table out loud — two T04s is an operational
    bug, not a cosmetic one. Enforced in the service (no DB constraint yet)."""
    stmt = select(func.count()).where(
        DiningTable.restaurant_id == restaurant_id,
        DiningTable.archived_at.is_(None),
        func.lower(DiningTable.label) == label.strip().lower(),
    )
    if exclude_id is not None:
        stmt = stmt.where(DiningTable.id != exclude_id)
    if (await session.scalar(stmt)) or 0:
        raise DuplicateTableLabelError(f"table {label} already exists")


async def update_table(
    session: AsyncSession,
    *,
    restaurant_id: int,
    table_id: int,
    label: str | None = None,
    seats: int | None = None,
    pos_x: float | None = None,
    pos_y: float | None = None,
    rotation: float | None = None,
) -> DiningTable:
    table = await _owned_table(session, restaurant_id=restaurant_id, table_id=table_id)
    if label is not None and label.strip() != table.label:
        await assert_label_free(
            session, restaurant_id=restaurant_id, label=label, exclude_id=table_id
        )
        table.label = label.strip()
    if seats is not None:
        table.seats = seats
    if pos_x is not None:
        table.pos_x = pos_x
    if pos_y is not None:
        table.pos_y = pos_y
    if rotation is not None:
        # Normalise to [0, 360) so repeated nudges never drift to 1080°.
        table.rotation = rotation % 360
    await session.flush()
    return table


async def archive_table(
    session: AsyncSession, *, restaurant_id: int, table_id: int
) -> DiningTable:
    """Soft delete — see DiningTable.archived_at. Refuses while a tab is open so
    a manager cannot make an unpaid order unreachable from the floor."""
    from app.ordering.order_types import OPEN_ORDER_STATUSES

    table = await _owned_table(session, restaurant_id=restaurant_id, table_id=table_id)
    open_count = await session.scalar(
        select(func.count()).where(
            Order.restaurant_id == restaurant_id,
            Order.table_id == table_id,
            Order.status.in_(OPEN_ORDER_STATUSES),
        )
    )
    if open_count:
        raise TableInUseError(f"table {table.label} still has an open order")
    table.archived_at = datetime.now(timezone.utc)
    await session.flush()
    return table


async def transition_status(
    session: AsyncSession, *, table_id: int, restaurant_id: int, to_status: str
) -> DiningTable:
    table = await session.get(DiningTable, table_id)
    if table is None or table.restaurant_id != restaurant_id:
        raise TableNotFoundError(f"table {table_id} not found")
    if to_status not in _TRANSITIONS.get(table.status, set()):
        raise InvalidTableTransitionError(f"cannot move table from {table.status} to {to_status}")
    table.status = to_status
    await session.flush()
    return table


async def update_table_position(
    session: AsyncSession, *, restaurant_id: int, table_id: int, pos_x: float, pos_y: float
) -> DiningTable:
    table = await session.get(DiningTable, table_id)
    if table is None or table.restaurant_id != restaurant_id:
        raise TableNotFoundError(f"table {table_id} not found")
    table.pos_x = pos_x
    table.pos_y = pos_y
    await session.flush()
    return table


async def transfer_order(
    session: AsyncSession, *, order_id: int, restaurant_id: int, to_table_id: int
) -> Order:
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise TableNotFoundError(f"order {order_id} not found")
    order.table_id = to_table_id
    await session.flush()
    return order
