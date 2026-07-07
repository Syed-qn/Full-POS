from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.kds.models import CategoryStationDefault, KitchenStation, PrintJob
from app.menu.models import Dish
from app.ordering.models import OrderItem


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
