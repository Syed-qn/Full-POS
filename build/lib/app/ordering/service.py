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


def _compute_exclusion_hash(
    phone: str, receiver_name: str | None, address_id: int | None
) -> str:
    """Single source for exclusion hash format (phone:receiver:addr_id). Used by cancel and matcher."""
    receiver = (receiver_name or "").strip().lower()
    addr = str(address_id or "")
    return hashlib.sha256(f"{phone}:{receiver}:{addr}".encode()).hexdigest()


def is_excluded_for_resale(
    exclusion_hash: str | None,
    *,
    phone: str,
    receiver_name: str | None = None,
    address_id: int | None = None,
) -> bool:
    """Return True if this buyer (phone + person/address) is barred from this resale per spec §1 and §4.3.7.

    Used by dispatch offer matcher and conversation resale suggestion to enforce
    "excluded from same phone/person/address".
    """
    if not exclusion_hash:
        return False
    h = _compute_exclusion_hash(phone, receiver_name, address_id)
    return h == exclusion_hash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.menu.models import Dish
    from app.ordering.detail_schemas import OrderDetailOut


async def get_available_resale_orders(
    session: "AsyncSession",
    restaurant_id: int,
    phone: str,
    receiver_name: str | None = None,
    address_id: int | None = None,
) -> list[Order]:
    """Resale-offer matcher: returns on_resale orders for which the given buyer is NOT excluded.

    Enforces post-cook cancel exclusion (same phone/person/address hash) per spec §1/§4.3.7.
    Used by dispatch engine / conversation when suggesting resale fast orders.
    """
    resales = (
        await session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant_id,
                Order.status == OrderStatus.ON_RESALE,
            )
        )
    ).all()
    available: list[Order] = []
    for r in resales:
        if not is_excluded_for_resale(
            r.exclusion_hash, phone=phone, receiver_name=receiver_name, address_id=address_id
        ):
            available.append(r)
    return available


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
    # Merge into an existing line for the same dish + notes so the cart shows
    # "2x Mango Lassi" instead of two separate "1x" lines (matches how real
    # ordering apps present a cart).
    existing_line = (
        await session.scalars(
            select(OrderItem).where(
                OrderItem.order_id == order.id,
                OrderItem.dish_id == dish.id,
                OrderItem.notes.is_(notes) if notes is None else OrderItem.notes == notes,
            )
        )
    ).first()
    if existing_line is not None:
        existing_line.qty += qty
        item = existing_line
    else:
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


async def remove_item(
    session: "AsyncSession",
    *,
    order: Order,
    dish: "Dish",
    qty: int = 1,
) -> int:
    """Remove up to ``qty`` units of ``dish`` from ``order``; return units removed.

    Decrements existing line items for the dish (newest first). Lines that reach
    zero are deleted. Recalculates order totals. Returns 0 if the dish is not in
    the cart. Caller commits.
    """
    items = (
        await session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order.id, OrderItem.dish_id == dish.id)
            .order_by(OrderItem.id.desc())
        )
    ).all()

    remaining = max(0, qty)
    removed = 0
    for item in items:
        if remaining <= 0:
            break
        take = min(item.qty, remaining)
        item.qty -= take
        removed += take
        remaining -= take
        if item.qty <= 0:
            await session.delete(item)
    if removed == 0:
        return 0
    await session.flush()

    existing = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    subtotal = sum((i.price_aed * i.qty for i in existing), Decimal("0.00"))
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()
    return removed


async def set_item_qty(
    session: "AsyncSession",
    *,
    order: Order,
    dish_id: int,
    qty: int,
) -> OrderItem | None:
    """Set the quantity of ``dish_id`` in ``order`` to exactly ``qty``.

    Collapses any duplicate lines for the dish into one. ``qty <= 0`` removes
    the dish entirely. Recalculates totals. Returns the surviving line (or None
    if the dish was not in the cart, or was removed). Caller commits.

    Used by the "make it 3" / "change to 2" context-update intercept.
    """
    items = (
        await session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order.id, OrderItem.dish_id == dish_id)
            .order_by(OrderItem.id)
        )
    ).all()
    if not items:
        return None

    survivor: OrderItem | None = None
    if qty <= 0:
        for item in items:
            await session.delete(item)
    else:
        survivor = items[0]
        survivor.qty = qty
        for extra in items[1:]:  # collapse duplicates
            await session.delete(extra)
    await session.flush()

    remaining = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    subtotal = sum((i.price_aed * i.qty for i in remaining), Decimal("0.00"))
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()
    return survivor


def parse_qty_and_text(text: str) -> tuple[int, str]:
    """Parse quantity prefixes from free text. Returns (qty, remaining_text).

    Handles: "2x chicken", "x2 chicken", "two chicken", "2 chicken",
    "make it 2 chicken", "chicken" (qty=1).
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
    # "2 201" — qty followed by a bare dish number (3+ digits)
    m = re.match(r"^(\d+)\s+(\d{3,})$", text)
    if m:
        qty = int(m.group(1))
        if 1 <= qty <= 20:
            return qty, m.group(2)

    # Natural: "2 biryani" or "make it 2 biryani" — find rightmost plausible qty
    m = re.search(r"\b(\d+)\s+([a-zA-Z؀-ۿ].+)$", text)
    if m:
        qty = int(m.group(1))
        if 1 <= qty <= 20:  # dish numbers are 100+ so small ints are quantities
            return qty, m.group(2).strip()
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
        # Spec §3: exclude same phone/PERSON/address — receiver_name covers the
        # person dimension (different address or phone, same receiver = still barred).
        receiver = ""
        if order.address_id is not None:
            address = await session.get(CustomerAddress, order.address_id)
            receiver = (address.receiver_name or "").strip().lower() if address else ""
        exclusion_hash = _compute_exclusion_hash(phone, receiver, order.address_id)
        # Resale exclusion enforced via is_excluded_for_resale (single hash source above).
        # Matcher (get_available_resale_orders) filters buyers against exclusion_hash when offering.

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


# Manager-driven kitchen status transitions: confirmed→preparing, preparing→ready.
_KITCHEN_TRANSITIONS: dict[OrderStatus, OrderStatus] = {
    OrderStatus.CONFIRMED: OrderStatus.PREPARING,
    OrderStatus.PREPARING: OrderStatus.READY,
}


async def advance_kitchen_status(
    session: "AsyncSession",
    *,
    order: Order,
    actor: str = "manager",
) -> Order:
    """Advance order through kitchen FSM: confirmed→preparing or preparing→ready.

    Raises ValueError if the order is not in a kitchen-advanceable state.
    """
    next_status = _KITCHEN_TRANSITIONS.get(OrderStatus(order.status))
    if next_status is None:
        raise ValueError(
            f"Cannot advance kitchen status from '{order.status}'. "
            f"Only confirmed or preparing orders can be advanced."
        )
    await fsm_transition(session, order, next_status, actor=actor)
    await session.commit()
    await session.refresh(order)
    return order


async def create_manual_order(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_phone: str,
    customer_name: str | None,
    items: list[dict],
    apt_room: str,
    building: str,
    receiver_name: str,
    address_notes: str | None,
    delivery_fee_aed: Decimal,
) -> "Order":
    """Create a confirmed delivery order on behalf of a walk-in/phone customer.

    Bypasses the WhatsApp conversation flow. Sends a WhatsApp confirmation
    via the outbox system. Caller must commit after this returns.
    """
    from app.menu.models import Dish, Menu
    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    # 1. Verify active menu exists
    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if not menu:
        raise ValueError("No active menu for this restaurant")

    # 2. Validate all dishes upfront
    validated: list[tuple] = []
    for item in items:
        dish = await session.scalar(
            select(Dish).where(
                Dish.id == item["dish_id"],
                Dish.restaurant_id == restaurant_id,
                Dish.is_available.is_(True),
            )
        )
        if not dish:
            raise ValueError(f"Dish {item['dish_id']} not found or unavailable")
        validated.append((dish, item["qty"], item.get("notes")))

    # 3. Get or create customer; only set name if customer is new
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=customer_phone
    )
    if customer_name and customer.name is None:
        customer.name = customer_name
        await session.flush()

    # 4. Store delivery address
    address = await upsert_address(
        session,
        customer_id=customer.id,
        latitude=None,
        longitude=None,
        room_apartment=apt_room,
        building=building,
        receiver_name=receiver_name,
        additional_details=address_notes,
        confirmed=True,
    )

    # 5. Create draft order and wire address + delivery fee
    order = await create_draft_order(
        session, restaurant_id=restaurant_id, customer_id=customer.id
    )
    order.delivery_fee_aed = delivery_fee_aed
    order.address_id = address.id
    await session.flush()

    # 6. Add items (each call recalculates subtotal)
    for dish, qty, notes in validated:
        await add_item(session, order=order, dish=dish, qty=qty, notes=notes)

    # 7. Recompute total including delivery fee (add_item only tracks subtotal)
    order.total = order.subtotal + delivery_fee_aed
    await session.flush()

    # 8. Confirm order (draft → pending_confirmation → confirmed, starts SLA)
    await finalize_confirmation(session, order=order, actor="manager")

    # 9. Enqueue WhatsApp confirmation to customer
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=customer_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={
            "body": (
                f"Your order {order.order_number} has been placed! "
                f"Total: AED {order.total} (COD). "
                f"Your food will arrive in ~40 minutes \U0001f6f5"
            )
        },
        idempotency_key=f"manual-order-confirm-{order.id}",
    )

    return order


async def get_order_detail(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    order_id: int,
) -> OrderDetailOut:
    """Assemble all data for the Order Detail drawer in one call."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.audit.models import AuditLog
    from app.conversation.models import Conversation, Message
    from app.dispatch.models import Assignment, RiderLocation
    from app.identity.models import Rider
    from app.marketing.optout import is_opted_out
    from app.ordering.detail_schemas import (
        AddressDetailOut,
        ChatMessageOut,
        CustomerDetailOut,
        GpsPingOut,
        OrderDetailOut,
        OrderItemDetailOut,
        RiderDetailOut,
        TimelineEventOut,
    )

    # 1. Order — raise if wrong tenant or unknown id
    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.restaurant_id == restaurant_id)
    )
    if not order:
        raise ValueError("Order not found")

    # 2. Items
    items_rows = list(
        (await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    )
    items = [
        OrderItemDetailOut(
            dish_number=i.dish_number,
            dish_name=i.dish_name,
            qty=i.qty,
            price_aed=i.price_aed,
        )
        for i in items_rows
    ]

    # 3. Customer
    customer = await session.get(Customer, order.customer_id)
    if not customer:
        raise ValueError("Order not found")

    # 4. Address
    address: AddressDetailOut | None = None
    if order.address_id:
        addr = await session.get(CustomerAddress, order.address_id)
        if addr:
            address = AddressDetailOut(
                id=addr.id,
                room_apartment=addr.room_apartment,
                building=addr.building,
                receiver_name=addr.receiver_name,
                additional_details=addr.additional_details,
                latitude=addr.latitude,
                longitude=addr.longitude,
            )

    # 5. Rider
    rider: RiderDetailOut | None = None
    if order.rider_id:
        r = await session.get(Rider, order.rider_id)
        if r:
            rider = RiderDetailOut(id=r.id, name=r.name, phone=r.phone)

    # 6. Timeline from audit log
    audit_rows = list(
        (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.entity == "order", AuditLog.entity_id == str(order.id))
                .order_by(AuditLog.created_at)
            )
        ).all()
    )
    timeline = [
        TimelineEventOut(
            ts=row.created_at,
            action=row.action,
            actor=row.actor,
            after=row.after,
        )
        for row in audit_rows
    ]

    # 7. Chat history — matched by customer phone on the customer-side conversation
    chat: list[ChatMessageOut] = []
    if customer:
        conv = await session.scalar(
            select(Conversation).where(
                Conversation.restaurant_id == restaurant_id,
                Conversation.phone == customer.phone,
                Conversation.counterpart == "customer",
            )
        )
        if conv:
            msg_rows = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == conv.id)
                        .order_by(Message.ts)
                    )
                ).all()
            )
            chat = [
                ChatMessageOut(
                    direction=m.direction,
                    text=m.payload.get("text") if m.type == "text" else None,
                    ts=m.ts,
                )
                for m in msg_rows
            ]

    # 8. Rider GPS route — pings between assignment time and delivery (or now)
    route: list[GpsPingOut] = []
    if order.rider_id:
        assignment = await session.scalar(
            select(Assignment).where(Assignment.order_id == order.id)
        )
        if assignment:
            upper = order.delivered_at or datetime.now(timezone.utc)
            ping_rows = list(
                (
                    await session.scalars(
                        select(RiderLocation)
                        .where(
                            RiderLocation.rider_id == order.rider_id,
                            RiderLocation.restaurant_id == restaurant_id,
                            RiderLocation.ts >= assignment.assigned_at,
                            RiderLocation.ts <= upper,
                        )
                        .order_by(RiderLocation.ts)
                    )
                ).all()
            )
            route = [
                GpsPingOut(latitude=p.latitude, longitude=p.longitude, ts=p.ts)
                for p in ping_rows
            ]

    # 9. Marketing opt-in flag
    opted_out = (
        await is_opted_out(session, restaurant_id=restaurant_id, phone=customer.phone)
        if customer
        else False
    )

    return OrderDetailOut(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        items=items,
        address=address,
        customer=CustomerDetailOut(
            id=customer.id,
            name=customer.name,
            phone=customer.phone,
            total_orders=customer.total_orders,
            total_spend=customer.total_spend,
            first_order_at=customer.first_order_at,
            last_order_at=customer.last_order_at,
            marketing_opted_in=not opted_out,
        ),
        rider=rider,
        subtotal=order.subtotal,
        delivery_fee_aed=order.delivery_fee_aed,
        total=order.total,
        created_at=order.created_at,
        delivered_at=order.delivered_at,
        sla_deadline=order.sla_deadline,
        timeline=timeline,
        chat=chat,
        route=route,
    )


async def patch_customer(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
    name: str | None,
    phone: str | None,
    marketing_opted_in: bool | None,
) -> Customer:
    """Update customer name/phone and/or marketing opt preference."""
    from sqlalchemy import select as sa_select
    from app.marketing.optout import record_opt_in, record_opt_out

    customer = await session.scalar(
        sa_select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant_id,
        )
    )
    if not customer:
        raise ValueError("Customer not found")

    # Capture phone BEFORE mutation so marketing opt targets the current phone
    effective_phone = customer.phone

    if name is not None:
        customer.name = name
    if phone is not None:
        customer.phone = phone
    if marketing_opted_in is True:
        await record_opt_in(session, restaurant_id=restaurant_id, phone=effective_phone)
    elif marketing_opted_in is False:
        await record_opt_out(
            session, restaurant_id=restaurant_id,
            phone=effective_phone, source="manager_dashboard",
        )

    await session.flush()
    return customer


async def patch_address(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
    address_id: int,
    room_apartment: str | None,
    building: str | None,
    receiver_name: str | None,
    additional_details: str | None,
) -> CustomerAddress:
    """Update address fields. Raises ValueError if address not owned by customer."""
    from sqlalchemy import select as sa_select

    # Verify the customer belongs to this restaurant tenant, then check address
    # ownership. Both failures surface as "Address not found" so that callers
    # cannot enumerate customer IDs across tenants.
    customer = await session.scalar(
        sa_select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant_id,
        )
    )

    addr = await session.scalar(
        sa_select(CustomerAddress).where(
            CustomerAddress.id == address_id,
            CustomerAddress.customer_id == customer_id,
        )
    ) if customer else None

    if not addr:
        raise ValueError("Address not found")

    if room_apartment is not None:
        addr.room_apartment = room_apartment
    if building is not None:
        addr.building = building
    if receiver_name is not None:
        addr.receiver_name = receiver_name
    if additional_details is not None:
        addr.additional_details = additional_details

    await session.flush()
    return addr
