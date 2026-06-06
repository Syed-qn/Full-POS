from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from app.audit.service import record_audit
from app.ordering.fsm import OrderStatus
from app.ordering.fsm import transition as fsm_transition
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.menu.models import Dish


async def get_order_for_tenant(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    order_id: int,
) -> Order | None:
    """Fetch a single order scoped to the tenant. Returns None if not found."""
    return await session.scalar(
        select(Order).where(
            Order.id == order_id,
            Order.restaurant_id == restaurant_id,
        )
    )


async def list_orders_for_tenant(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    status: str | None = None,
    limit: int = 50,
) -> list[Order]:
    """List orders for the tenant, newest first, optionally filtered by status.

    ``limit`` is clamped to the inclusive range [1, 100] to bound result size.
    """
    limit = min(max(limit, 1), 100)
    q = select(Order).where(Order.restaurant_id == restaurant_id)
    if status:
        q = q.where(Order.status == status)
    q = q.order_by(Order.created_at.desc()).limit(limit)
    return list((await session.scalars(q)).all())


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


# Statuses at/after which the kitchen is locked in — modification is forbidden.
_NON_MODIFIABLE_STATUSES = {
    OrderStatus.READY,
    OrderStatus.ASSIGNED,
    OrderStatus.PICKED_UP,
    OrderStatus.ARRIVING,
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.UNDELIVERABLE,
    OrderStatus.ON_RESALE,
    OrderStatus.RESOLD,
    OrderStatus.WRITTEN_OFF,
}


async def modify_order(
    session: "AsyncSession",
    *,
    order: Order,
    new_items: list[dict],
    actor: str,
) -> None:
    """Replace all items on an order, recalculate totals, restart the SLA clock.

    Allowed only before status reaches 'ready' (spec §4.5). Once the customer
    confirms the modification the 40-minute clock restarts. Caller must commit.
    """
    if order.status in _NON_MODIFIABLE_STATUSES:
        raise ValueError(
            f"Order modification not allowed at status '{order.status}'. "
            f"Modifications are blocked once an order reaches 'ready'."
        )

    before_snapshot = {
        "status": str(order.status),
        "subtotal": str(order.subtotal),
        "total": str(order.total),
        "sla_deadline": order.sla_deadline.isoformat() if order.sla_deadline else None,
    }

    existing_items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    for item in existing_items:
        await session.delete(item)
    await session.flush()

    subtotal = Decimal("0.00")
    for entry in new_items:
        dish = entry["dish"]
        qty = entry.get("qty", 1)
        notes = entry.get("notes")
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
        subtotal += dish.price_aed * qty

    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed

    # Restart the SLA clock after the customer confirms the modification.
    now = datetime.now(timezone.utc)
    order.sla_confirmed_at = now
    order.sla_deadline = now + timedelta(minutes=40)
    order.promised_eta = order.sla_deadline
    await session.flush()

    await record_audit(
        session,
        actor=actor,
        restaurant_id=order.restaurant_id,
        entity="order",
        entity_id=str(order.id),
        action="order_modified",
        before=before_snapshot,
        after={
            "subtotal": str(order.subtotal),
            "total": str(order.total),
            "sla_deadline": order.sla_deadline.isoformat(),
        },
    )


async def cancel_order(
    session: "AsyncSession",
    *,
    order: Order,
    actor: str,
    reason: str | None = None,
) -> Order | None:
    """Cancel an order.

    Before cooking (status != preparing) → plain transition to CANCELLED.
    After cooking started (status == preparing) → transition original to
    ON_RESALE and create a resale copy carrying an exclusion hash so the same
    phone/address combination is barred from buying the resold food.

    Returns the resale Order if one was created, else None. Caller must commit.
    """
    order.cancellation_reason = reason
    order.cancelled_at = datetime.now(timezone.utc)

    if order.status == OrderStatus.PREPARING:
        await fsm_transition(
            session, order, OrderStatus.ON_RESALE, actor=actor,
            extra_audit={"reason": reason or ""},
        )

        customer = await session.get(Customer, order.customer_id)
        phone = customer.phone if customer else ""
        addr_id = str(order.address_id or "")
        # Spec §3: exclude same phone/PERSON/address — receiver_name covers the
        # person dimension (different address or phone, same receiver = still barred).
        receiver = ""
        if order.address_id is not None:
            address = await session.get(CustomerAddress, order.address_id)
            receiver = (address.receiver_name or "").strip().lower() if address else ""
        exclusion_hash = hashlib.sha256(
            f"{phone}:{receiver}:{addr_id}".encode()
        ).hexdigest()
        # TODO(phase-4 resale dispatch): the resale-offer matcher MUST filter
        # candidate buyers against this exclusion_hash — written here, enforced
        # nowhere yet. See understanding.txt Wave-4 review fix #2.

        resale = Order(
            restaurant_id=order.restaurant_id,
            customer_id=order.customer_id,
            order_number=f"{order.order_number}-RS",
            status=OrderStatus.ON_RESALE,
            priority=order.priority,
            weather_delay_disclosed=order.weather_delay_disclosed,
            delivery_fee_aed=order.delivery_fee_aed,
            subtotal=order.subtotal,
            total=order.total,
            address_id=order.address_id,
            distance_km=order.distance_km,
            additional_details=order.additional_details,
            resale_of_order_id=order.id,
            exclusion_hash=exclusion_hash,
        )
        session.add(resale)
        await session.flush()
        return resale

    await fsm_transition(
        session, order, OrderStatus.CANCELLED, actor=actor,
        extra_audit={"reason": reason or ""},
    )
    return None
