from collections import defaultdict
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.aggregators.port import AggregatorPort
from app.menu.models import Dish, Menu
from app.ordering.models import Order, OrderItem
from app.ordering.service import get_or_create_customer


async def _get_or_create_active_menu(session: AsyncSession, *, restaurant_id: int) -> Menu:
    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
    if menu is not None:
        return menu
    menu = Menu(restaurant_id=restaurant_id, version=1, status="active", source_files=[])
    session.add(menu)
    await session.flush()
    return menu


async def _get_or_create_dish(session: AsyncSession, *, restaurant_id: int, menu_id: int, name: str, price_aed: Decimal) -> Dish:
    normalized = name.strip().lower()
    dish = await session.scalar(
        select(Dish).where(Dish.restaurant_id == restaurant_id, Dish.name_normalized == normalized)
    )
    if dish is not None:
        return dish
    max_number = await session.scalar(
        select(Dish.dish_number).where(Dish.restaurant_id == restaurant_id).order_by(Dish.dish_number.desc()).limit(1)
    )
    dish = Dish(
        menu_id=menu_id, restaurant_id=restaurant_id, dish_number=(max_number or 0) + 1,
        name=name, price_aed=price_aed, category="Aggregator Import", is_available=True,
        name_normalized=normalized,
    )
    session.add(dish)
    await session.flush()
    return dish


async def ingest_inbound_order(
    session: AsyncSession, *, restaurant_id: int, provider: str, payload: dict, gateway: AggregatorPort,
) -> Order:
    parsed = gateway.parse_inbound(payload)
    customer = await get_or_create_customer(session, restaurant_id=restaurant_id, phone=parsed.customer_phone)
    menu = await _get_or_create_active_menu(session, restaurant_id=restaurant_id)

    order = Order(
        restaurant_id=restaurant_id, customer_id=customer.id,
        order_number=f"{provider.upper()}-{parsed.provider_order_ref}",
        status="confirmed", subtotal=parsed.total_aed, total=parsed.total_aed,
        aggregator_source=provider, aggregator_order_ref=parsed.provider_order_ref,
    )
    session.add(order)
    await session.flush()

    for item in parsed.items:
        dish = await _get_or_create_dish(
            session, restaurant_id=restaurant_id, menu_id=menu.id, name=item.dish_name, price_aed=item.price_aed,
        )
        session.add(OrderItem(
            order_id=order.id, dish_id=dish.id, dish_number=dish.dish_number, dish_name=item.dish_name,
            price_aed=item.price_aed, qty=item.qty,
        ))
    await session.flush()
    return order


async def reconciliation(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date,
) -> dict:
    day_start = datetime.combine(start_date, time.min)
    day_end = datetime.combine(end_date, time.max)
    orders = (await session.scalars(
        select(Order).where(
            Order.restaurant_id == restaurant_id,
            Order.aggregator_source.is_not(None),
            Order.created_at >= day_start, Order.created_at <= day_end,
        )
    )).all()

    result: dict[str, dict] = defaultdict(lambda: {"order_count": 0, "revenue_aed": Decimal("0.00")})
    for order in orders:
        entry = result[order.aggregator_source]
        entry["order_count"] += 1
        entry["revenue_aed"] += order.total
    return dict(result)
