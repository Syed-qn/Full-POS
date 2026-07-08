from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kds.models import CategoryStationDefault, KitchenStation, PrintJob
from app.menu.models import Dish
from app.ordering.models import Order, OrderItem


async def get_or_create_main_station(session: AsyncSession, *, restaurant_id: int) -> KitchenStation:
    existing = await session.scalar(
        select(KitchenStation).where(
            KitchenStation.restaurant_id == restaurant_id, KitchenStation.name == "Main"
        )
    )
    if existing is not None:
        return existing
    station = KitchenStation(restaurant_id=restaurant_id, name="Main")
    session.add(station)
    await session.flush()
    return station


async def resolve_station(session: AsyncSession, *, restaurant_id: int, dish) -> int:
    """dish override -> category default -> auto-created 'Main' fallback."""
    if dish.station_id is not None:
        return dish.station_id
    if dish.category:
        default = await session.scalar(
            select(CategoryStationDefault).where(
                CategoryStationDefault.restaurant_id == restaurant_id,
                CategoryStationDefault.category == dish.category,
            )
        )
        if default is not None:
            return default.station_id
    main = await get_or_create_main_station(session, restaurant_id=restaurant_id)
    return main.id


async def create_tickets_for_order(session: AsyncSession, *, restaurant_id: int, order) -> None:
    items = (await session.scalars(
        select(OrderItem).where(OrderItem.order_id == order.id)
    )).all()
    by_station: dict[int, list[OrderItem]] = defaultdict(list)
    for item in items:
        dish = await session.get(Dish, item.dish_id)
        station_id = await resolve_station(session, restaurant_id=restaurant_id, dish=dish)
        item.kitchen_status = "received"
        item.station_id_snapshot = station_id
        by_station[station_id].append(item)

    for station_id, station_items in by_station.items():
        lines = "\n".join(
            f"{i.qty}x {i.dish_name}" + (f" ({i.variant_name})" if i.variant_name else "")
            for i in station_items
        )
        payload = f"Order {order.order_number}\n{lines}"
        session.add(PrintJob(
            restaurant_id=restaurant_id, station_id=station_id, order_id=order.id,
            payload=payload, status="pending",
        ))


async def _get_tenant_order_item(
    session: AsyncSession, *, restaurant_id: int, order_item_id: int
) -> OrderItem:
    item = await session.get(OrderItem, order_item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    order = await session.get(Order, item.order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise HTTPException(status_code=404, detail="item not found")
    return item


async def mark_packaging_checked(
    session: AsyncSession, *, restaurant_id: int, order_item_id: int
) -> OrderItem:
    item = await _get_tenant_order_item(
        session, restaurant_id=restaurant_id, order_item_id=order_item_id
    )
    item.packaging_checked = True
    await session.flush()
    return item


async def mark_quality_checked(
    session: AsyncSession, *, restaurant_id: int, order_item_id: int
) -> OrderItem:
    item = await _get_tenant_order_item(
        session, restaurant_id=restaurant_id, order_item_id=order_item_id
    )
    item.quality_checked = True
    await session.flush()
    return item


async def list_ready_for_pickup(
    session: AsyncSession, *, restaurant_id: int
) -> dict[int, list[OrderItem]]:
    """Ready-but-not-yet-picked-up items, grouped by order id, for the tenant.

    "Ready" reuses the existing kitchen_status FSM value set by bump_item — no new
    status string is introduced. bump_item leaves items at "ready" until dispatch/
    pickup moves the order itself along; this just lists what's currently sitting there.
    """
    rows = (await session.scalars(
        select(OrderItem)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.restaurant_id == restaurant_id, OrderItem.kitchen_status == "ready")
        .order_by(OrderItem.order_id, OrderItem.id)
    )).all()
    by_order: dict[int, list[OrderItem]] = defaultdict(list)
    for item in rows:
        by_order[item.order_id].append(item)
    return by_order
