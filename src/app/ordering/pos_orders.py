"""POS order-management operations (Category 1 completion).

Covers multi-type create (dine-in/takeaway/drive-thru/tableside/online/delivery),
hold/unhold, priority/rush, course fire, open/held listing helpers, refund-order,
and repeat-last-order. WhatsApp draft creation stays in ``service.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.ordering.fsm import OrderStatus
from app.ordering.models import Order, OrderItem
from app.ordering.order_types import (
    OPEN_ORDER_STATUSES,
    ORDER_TYPE_DELIVERY,
    PRIORITY_RUSH,
    requires_address,
    requires_table,
    validate_order_type,
    validate_priority,
)

if TYPE_CHECKING:
    from app.menu.models import Dish


_HOLDABLE = {
    OrderStatus.DRAFT,
    OrderStatus.PENDING_CONFIRMATION,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
}


async def create_pos_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_type: str,
    customer_phone: str,
    customer_name: str | None,
    items: list[dict],
    table_id: int | None = None,
    staff_id: int | None = None,
    apt_room: str | None = None,
    building: str | None = None,
    receiver_name: str | None = None,
    address_notes: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    delivery_fee_aed: Decimal = Decimal("0.00"),
    scheduled_for: datetime | None = None,
    is_preorder: bool = False,
    priority: str = "normal",
    customer_allergy_notes: str | None = None,
    auto_confirm: bool = True,
) -> Order:
    """Create a POS order of any supported ``order_type``.

    ``items`` entries: ``{dish_id, qty, notes?, course_number?, course_held?, seat_number?}``.
    Address fields are required only for delivery/online/aggregator types.
    Table is required for dine_in/qr/tableside.
    Future ``scheduled_for`` without auto-release leaves the order draft until
    ``release_scheduled_orders`` (or explicit confirm).
    """
    from app.menu.models import Dish, Menu
    from app.menu.service import is_dish_currently_available
    from app.ordering.service import (
        add_item,
        create_draft_order,
        finalize_confirmation,
        get_or_create_customer,
        upsert_address,
    )
    from app.tables.models import DiningTable

    order_type = validate_order_type(order_type)
    priority = validate_priority(priority)

    if not items:
        raise ValueError("Cannot place an order with no items")

    menu = await session.scalar(
        select(Menu).where(Menu.restaurant_id == restaurant_id, Menu.status == "active")
    )
    if not menu:
        raise ValueError("No active menu for this restaurant")

    if requires_table(order_type):
        if table_id is None:
            raise ValueError(f"{order_type} orders require table_id")
        table = await session.get(DiningTable, table_id)
        if table is None or table.restaurant_id != restaurant_id:
            raise ValueError("table not found")
    elif table_id is not None:
        table = await session.get(DiningTable, table_id)
        if table is None or table.restaurant_id != restaurant_id:
            raise ValueError("table not found")

    if requires_address(order_type):
        if not (building and apt_room and receiver_name):
            raise ValueError(f"{order_type} orders require address (apt_room, building, receiver_name)")

    validated: list[tuple[Dish, int, str | None, int, bool, int | None]] = []
    today = datetime.now(timezone.utc).date()
    for raw in items:
        dish = await session.scalar(
            select(Dish).where(
                Dish.id == raw["dish_id"],
                Dish.restaurant_id == restaurant_id,
                Dish.is_available.is_(True),
            )
        )
        if dish is not None and not is_dish_currently_available(dish, today=today):
            dish = None
        if not dish:
            raise ValueError(f"Dish {raw['dish_id']} not found or unavailable")
        course_number = int(raw.get("course_number") or 1)
        if course_number < 1:
            raise ValueError("course_number must be >= 1")
        course_held = bool(raw.get("course_held", False))
        seat_number = raw.get("seat_number")
        seat_number = int(seat_number) if seat_number is not None else None
        validated.append(
            (dish, int(raw["qty"]), raw.get("notes"), course_number, course_held, seat_number)
        )

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=customer_phone
    )
    if customer_name and customer.name is None:
        customer.name = customer_name

    allergy = customer_allergy_notes
    if allergy is None:
        allergy = customer.allergy_notes

    order = await create_draft_order(
        session, restaurant_id=restaurant_id, customer_id=customer.id
    )
    order.order_type = order_type
    order.priority = priority
    order.table_id = table_id
    order.staff_id = staff_id
    order.customer_allergy_notes = allergy
    order.scheduled_for = scheduled_for
    order.is_preorder = bool(is_preorder or scheduled_for is not None)
    order.delivery_fee_aed = (
        Decimal("0.00") if not requires_address(order_type) else delivery_fee_aed
    )
    # Training-mode staff → training orders (excluded from real sales KPIs).
    if staff_id is not None:
        from app.staff.models import StaffMember

        member = await session.get(StaffMember, staff_id)
        if member is not None and member.restaurant_id == restaurant_id and member.training_mode:
            order.is_training = True

    if requires_address(order_type):
        from app.ordering.service import _geocode_manual_address

        if latitude is not None and longitude is not None:
            lat, lng = latitude, longitude
        else:
            lat, lng = await _geocode_manual_address(session, restaurant_id, building or "")
        address = await upsert_address(
            session,
            customer_id=customer.id,
            latitude=lat,
            longitude=lng,
            room_apartment=apt_room or "",
            building=building or "",
            receiver_name=receiver_name or "",
            additional_details=address_notes,
            confirmed=True,
        )
        order.address_id = address.id

    await session.flush()

    for dish, qty, notes, course_number, course_held, seat_number in validated:
        item = await add_item(
            session,
            order=order,
            dish=dish,
            qty=qty,
            notes=notes,
            course_number=course_number,
            course_held=course_held,
        )
        item.seat_number = seat_number

    order.total = order.subtotal + (order.delivery_fee_aed or Decimal("0.00"))
    await session.flush()

    # Future scheduled: keep as draft until release job; manager can still list it.
    now = datetime.now(timezone.utc)
    defer_confirm = (
        scheduled_for is not None
        and scheduled_for > now
        and auto_confirm
    )
    if auto_confirm and not defer_confirm:
        await finalize_confirmation(session, order=order, actor="manager")
        order.scheduled_released_at = now

    if requires_table(order_type) and table_id is not None:
        table = await session.get(DiningTable, table_id)
        if table is not None and table.status == "available":
            table.status = "ordered" if order.status != OrderStatus.DRAFT else "seated"

    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="manager",
        entity="order",
        entity_id=str(order.id),
        action="pos_order_created",
        after={
            "order_type": order_type,
            "priority": priority,
            "scheduled_for": scheduled_for.isoformat() if scheduled_for else None,
            "is_preorder": order.is_preorder,
        },
    )
    await session.flush()
    return order


async def hold_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    reason: str | None = None,
) -> Order:
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError("Order not found")
    if order.status not in {s.value for s in _HOLDABLE}:
        raise ValueError(f"cannot hold order in status {order.status!r}")
    if order.held_at is not None:
        raise ValueError("order is already held")
    order.held_at = datetime.now(timezone.utc)
    order.held_reason = reason
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="manager",
        entity="order",
        entity_id=str(order.id),
        action="held",
        after={"reason": reason},
    )
    await session.flush()
    return order


async def unhold_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
) -> Order:
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError("Order not found")
    if order.held_at is None:
        raise ValueError("order is not held")
    order.held_at = None
    order.held_reason = None
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="manager",
        entity="order",
        entity_id=str(order.id),
        action="unheld",
        after={},
    )
    await session.flush()
    return order


async def set_order_priority(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    priority: str,
) -> Order:
    priority = validate_priority(priority)
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError("Order not found")
    before = order.priority
    order.priority = priority
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="manager",
        entity="order",
        entity_id=str(order.id),
        action="priority_set",
        before={"priority": before},
        after={"priority": priority},
    )
    await session.flush()
    return order


async def mark_rush(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
) -> Order:
    return await set_order_priority(
        session, restaurant_id=restaurant_id, order_id=order_id, priority=PRIORITY_RUSH
    )


async def fire_course(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    course_number: int,
) -> list[OrderItem]:
    """Fire all held items on ``course_number`` to the kitchen (create tickets)."""
    from app.kds.service import create_tickets_for_items

    if course_number < 1:
        raise ValueError("course_number must be >= 1")
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError("Order not found")
    if order.held_at is not None:
        raise ValueError("cannot fire courses on a held order; unhold first")

    items = (
        await session.scalars(
            select(OrderItem).where(
                OrderItem.order_id == order.id,
                OrderItem.course_number == course_number,
                OrderItem.course_held.is_(True),
                OrderItem.cancelled.is_(False),
            )
        )
    ).all()
    if not items:
        raise ValueError(f"no held items for course {course_number}")

    now = datetime.now(timezone.utc)
    for item in items:
        item.course_held = False
        item.fired_at = now

    await create_tickets_for_items(
        session, restaurant_id=restaurant_id, order=order, items=list(items)
    )
    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="manager",
        entity="order",
        entity_id=str(order.id),
        action="course_fired",
        after={"course_number": course_number, "item_ids": [i.id for i in items]},
    )
    await session.flush()
    return list(items)


async def repeat_last_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_phone: str,
) -> Order:
    """Create a draft copy of the customer's most recent non-resale order."""
    from app.ordering.duplicate import duplicate_order
    from app.ordering.service import get_or_create_customer

    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=customer_phone
    )
    last = await session.scalar(
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.customer_id == customer.id,
            Order.resale_of_order_id.is_(None),
            Order.status.notin_(["draft"]),
        )
        .order_by(Order.created_at.desc())
        .limit(1)
    )
    if last is None:
        raise ValueError("no previous order to repeat")
    new_order = await duplicate_order(
        session, restaurant_id=restaurant_id, order_id=last.id
    )
    new_order.order_type = last.order_type or ORDER_TYPE_DELIVERY
    new_order.customer_allergy_notes = customer.allergy_notes
    await session.flush()
    return new_order


async def refund_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    reason: str | None = None,
    gateway=None,
) -> dict:
    """Refund all refundable payment tenders on the order (full remaining amounts).

    Returns a summary dict. Does not cancel the order FSM (caller may cancel
    separately); this is the POS "refund order" money path.
    """
    from app.payments.factory import get_payment_port
    from app.payments.models import PaymentTransaction
    from app.payments.service import refund_transaction

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError("Order not found")

    gw = gateway or get_payment_port()
    txns = (
        await session.scalars(
            select(PaymentTransaction).where(
                PaymentTransaction.order_id == order_id,
                PaymentTransaction.restaurant_id == restaurant_id,
                PaymentTransaction.status.in_(
                    ("succeeded", "partially_refunded", "refunded")
                ),
            )
        )
    ).all()

    refunded: list[dict] = []
    for txn in txns:
        remaining = txn.amount_aed - (txn.refunded_amount_aed or Decimal("0.00"))
        if remaining <= 0:
            continue
        updated = await refund_transaction(
            session,
            transaction_id=txn.id,
            restaurant_id=restaurant_id,
            amount_aed=remaining,
            gateway=gw,
        )
        refunded.append(
            {
                "transaction_id": updated.id,
                "amount_aed": str(remaining),
                "status": updated.status,
            }
        )

    if not refunded:
        raise ValueError("no refundable payments on this order")

    await record_audit(
        session,
        restaurant_id=restaurant_id,
        actor="manager",
        entity="order",
        entity_id=str(order.id),
        action="order_refunded",
        after={"reason": reason, "refunds": refunded},
    )
    await session.flush()
    return {"order_id": order.id, "refunds": refunded, "reason": reason}


async def list_open_orders(
    session: AsyncSession,
    *,
    restaurant_id: int,
    limit: int = 50,
) -> list[Order]:
    limit = min(max(limit, 1), 100)
    result = await session.scalars(
        select(Order)
        .where(
            Order.restaurant_id == restaurant_id,
            Order.status.in_(sorted(OPEN_ORDER_STATUSES)),
            Order.held_at.is_(None),
        )
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(result.all())


async def list_held_orders(
    session: AsyncSession,
    *,
    restaurant_id: int,
    limit: int = 50,
) -> list[Order]:
    limit = min(max(limit, 1), 100)
    result = await session.scalars(
        select(Order)
        .where(Order.restaurant_id == restaurant_id, Order.held_at.is_not(None))
        .order_by(Order.held_at.desc())
        .limit(limit)
    )
    return list(result.all())
