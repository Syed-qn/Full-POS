from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.ordering.fsm import OrderStatus
from app.ordering.fsm import transition as fsm_transition
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.menu.models import Dish


async def get_or_create_customer(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    phone: str,
) -> Customer:
    existing = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == phone,
        )
    )
    if existing:
        return existing
    customer = Customer(
        restaurant_id=restaurant_id,
        phone=phone,
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    session.add(customer)
    await session.flush()
    return customer


async def get_last_address(
    session: "AsyncSession",
    customer_id: int,
) -> CustomerAddress | None:
    return await session.scalar(
        select(CustomerAddress)
        .where(
            CustomerAddress.customer_id == customer_id,
            CustomerAddress.confirmed == True,  # noqa: E712
        )
        .order_by(CustomerAddress.last_used_at.desc().nullslast())
        .limit(1)
    )


async def upsert_address(
    session: "AsyncSession",
    *,
    customer_id: int,
    latitude: float | None,
    longitude: float | None,
    room_apartment: str,
    building: str,
    receiver_name: str | None = None,
    additional_details: str | None = None,
    confirmed: bool = False,
) -> CustomerAddress:
    addr = CustomerAddress(
        customer_id=customer_id,
        latitude=latitude,
        longitude=longitude,
        room_apartment=room_apartment,
        building=building,
        receiver_name=receiver_name,
        additional_details=additional_details,
        confirmed=confirmed,
    )
    session.add(addr)
    await session.flush()
    return addr


async def create_draft_order(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
) -> Order:
    count = await session.scalar(
        select(func.count()).select_from(Order).where(Order.restaurant_id == restaurant_id)
    ) or 0
    order_number = f"R{restaurant_id}-{count + 1:04d}"
    order = Order(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_number=order_number,
        status=OrderStatus.DRAFT,
        priority="normal",
        weather_delay_disclosed=False,
        delivery_fee_aed=Decimal("0.00"),
        subtotal=Decimal("0.00"),
        total=Decimal("0.00"),
    )
    session.add(order)
    await session.flush()
    return order


async def add_item(
    session: "AsyncSession",
    *,
    order: Order,
    dish: "Dish",
    qty: int = 1,
    notes: str | None = None,
) -> OrderItem:
    item = OrderItem(
        order_id=order.id,
        dish_id=dish.id,
        dish_number=dish.dish_number,
        dish_name=dish.name,
        price_aed=dish.price_aed,
        qty=qty,
        notes=notes,
    )
    session.add(item)
    await session.flush()
    # Recalculate order totals from persisted items.
    existing = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    subtotal = sum((i.price_aed * i.qty for i in existing), Decimal("0.00"))
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()
    return item


def parse_qty_and_text(text: str) -> tuple[int, str]:
    """Parse quantity prefixes from free text. Returns (qty, remaining_text).

    Handles: "2x chicken", "x2 chicken", "two chicken", "chicken" (qty=1).
    """
    text = text.strip()
    m = re.match(r"^(\d+)\s*[xX]\s*(.+)$", text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    m = re.match(r"^[xX]\s*(\d+)\s+(.+)$", text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    lower = text.lower()
    for word, val in word_map.items():
        if lower.startswith(word + " "):
            return val, text[len(word):].strip()
    return 1, text


async def finalize_confirmation(
    session: "AsyncSession",
    *,
    order: Order,
    actor: str = "customer",
) -> None:
    """Move order draft → pending_confirmation → confirmed and start the SLA clock."""
    if order.status == OrderStatus.DRAFT:
        await fsm_transition(session, order, OrderStatus.PENDING_CONFIRMATION, actor=actor)
    if order.status == OrderStatus.PENDING_CONFIRMATION:
        await fsm_transition(session, order, OrderStatus.CONFIRMED, actor=actor)
    now = datetime.now(timezone.utc)
    order.sla_confirmed_at = now
    order.sla_deadline = now + timedelta(minutes=40)
    order.promised_eta = order.sla_deadline
    await session.flush()
