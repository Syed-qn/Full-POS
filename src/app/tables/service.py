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
