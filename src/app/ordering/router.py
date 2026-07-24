# src/app/ordering/router.py
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant, Rider
from app.staff.deps import current_actor, current_restaurant_any, require_role
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.ordering.schemas import (
    AddOrderItemsIn,
    AddressOut,
    CancelOrderIn,
    CancelOrderItemIn,
    CoversIn,
    CustomerLookupOut,
    DeliveryFailedIn,
    DeliveryPhotoIn,
    EditOrderItemIn,
    FireCourseIn,
    HoldOrderIn,
    ManualOrderIn,
    MergeOrdersIn,
    OrderItemOut,
    OrderOut,
    PosOrderIn,
    PriorityIn,
    ReassignOrderIn,
    RefundOrderIn,
    RepeatLastOrderIn,
    SplitOrderByItemsIn,
    SplitOrderBySeatIn,
    TransferOrderStaffIn,
    VerifyDeliveryOtpIn,
)
from app.ordering.detail_schemas import (
    OrderDetailOut,
)
from app.ordering.fsm import IllegalTransitionError
from app.loyalty.schemas import NpsResponseIn, NpsResponseOut
from app.ordering.service import (
    acknowledge_sla_breach,
    advance_kitchen_status,
    cancel_order,
    cancel_order_item,
    create_manual_order,
    delete_order,
    edit_order_item,
    get_last_address,
    get_order_detail,
    get_order_for_tenant,
    list_orders_for_tenant,
    merge_orders,
    parse_detail_includes,
    split_order_by_items,
    split_order_by_seat,
    transfer_order_staff,
)

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


def _order_item_out(i: OrderItem) -> OrderItemOut:
    return OrderItemOut(
        dish_number=i.dish_number,
        name=i.dish_name,
        qty=i.qty,
        price_aed=str(i.price_aed),
        variant_name=i.variant_name,
        notes=i.notes,
        cancelled=i.cancelled,
        cancelled_reason=i.cancelled_reason,
        course_number=getattr(i, "course_number", 1) or 1,
        course_held=bool(getattr(i, "course_held", False)),
        seat_number=getattr(i, "seat_number", None),
    )


def _address_parts(addr: CustomerAddress) -> tuple[str | None, float | None, float | None]:
    parts = [p for p in [addr.room_apartment, addr.building] if p]
    return ", ".join(parts) or None, addr.latitude, addr.longitude


async def _enrich_orders_bulk(
    session: AsyncSession,
    orders: list[Order],
    *,
    batch_preview: dict[int, str] | None = None,
) -> list[OrderOut]:
    """Join related rows for many orders in a constant number of queries."""
    if not orders:
        return []

    from app.dispatch.models import BatchOrder

    preview = batch_preview or {}
    order_ids = [o.id for o in orders]
    customer_ids = {o.customer_id for o in orders if o.customer_id is not None}
    rider_ids = {o.rider_id for o in orders if o.rider_id is not None}
    address_ids = {o.address_id for o in orders if o.address_id is not None}

    customers: dict[int, Customer] = {}
    if customer_ids:
        for c in (
            await session.scalars(select(Customer).where(Customer.id.in_(customer_ids)))
        ).all():
            customers[c.id] = c

    items_by_order: dict[int, list[OrderItem]] = defaultdict(list)
    for item in (
        await session.scalars(select(OrderItem).where(OrderItem.order_id.in_(order_ids)))
    ).all():
        items_by_order[item.order_id].append(item)

    riders: dict[int, Rider] = {}
    if rider_ids:
        for r in (
            await session.scalars(select(Rider).where(Rider.id.in_(rider_ids)))
        ).all():
            riders[r.id] = r

    addresses: dict[int, CustomerAddress] = {}
    if address_ids:
        for a in (
            await session.scalars(
                select(CustomerAddress).where(CustomerAddress.id.in_(address_ids))
            )
        ).all():
            addresses[a.id] = a

    nameless_customer_ids = [
        cid
        for cid in customer_ids
        if not (customers.get(cid) and (customers[cid].name or "").strip())
    ]
    fallback_receiver: dict[int, str] = {}
    if nameless_customer_ids:
        for a in (
            await session.scalars(
                select(CustomerAddress)
                .where(
                    CustomerAddress.customer_id.in_(nameless_customer_ids),
                    CustomerAddress.receiver_name.isnot(None),
                )
                .order_by(CustomerAddress.id.desc())
            )
        ).all():
            rn = (a.receiver_name or "").strip()
            if rn and a.customer_id not in fallback_receiver:
                fallback_receiver[a.customer_id] = rn

    batch_by_order: dict[int, BatchOrder] = {}
    for bo in (
        await session.scalars(select(BatchOrder).where(BatchOrder.order_id.in_(order_ids)))
    ).all():
        batch_by_order[bo.order_id] = bo

    batch_numbers_by_batch: dict[int, list[str]] = defaultdict(list)
    batch_ids = {bo.batch_id for bo in batch_by_order.values()}
    if batch_ids:
        for batch_id, order_number in (
            await session.execute(
                select(BatchOrder.batch_id, Order.order_number)
                .join(Order, Order.id == BatchOrder.order_id)
                .where(BatchOrder.batch_id.in_(batch_ids))
                .order_by(BatchOrder.batch_id, BatchOrder.sequence)
            )
        ).all():
            batch_numbers_by_batch[batch_id].append(order_number)

    out: list[OrderOut] = []
    for order in orders:
        customer = customers.get(order.customer_id) if order.customer_id else None
        customer_name = getattr(customer, "name", None) if customer else None
        customer_phone = customer.phone if customer else ""

        if order.address_id is not None and order.address_id in addresses:
            addr = addresses[order.address_id]
            if not (customer_name or "").strip() and addr.receiver_name:
                customer_name = addr.receiver_name

        if customer is not None and not (customer_name or "").strip():
            customer_name = fallback_receiver.get(customer.id)

        address_str: str | None = None
        lat: float | None = None
        lng: float | None = None
        if order.address_id is not None and order.address_id in addresses:
            address_str, lat, lng = _address_parts(addresses[order.address_id])

        rider_name = (
            riders[order.rider_id].name
            if order.rider_id is not None and order.rider_id in riders
            else None
        )

        bo = batch_by_order.get(order.id)
        batch_id = bo.batch_id if bo is not None else None
        batch_order_numbers = (
            batch_numbers_by_batch.get(batch_id, []) if batch_id is not None else []
        )

        out.append(
            OrderOut(
                id=order.id,
                order_number=order.order_number,
                daily_token=getattr(order, "daily_token", None),
                resale_of_order_id=order.resale_of_order_id,
                cancellation_reason=getattr(order, "cancellation_reason", None),
                status=str(order.status),
                customer_name=customer_name,
                customer_phone=customer_phone,
                items=[_order_item_out(i) for i in items_by_order.get(order.id, [])],
                total_aed=str(order.total),
                rider_id=order.rider_id,
                rider_name=rider_name,
                sla_started_at=(
                    order.sla_confirmed_at.isoformat() if order.sla_confirmed_at else None
                ),
                prep_deadline=(
                    order.prep_deadline.isoformat() if order.prep_deadline else None
                ),
                cook_estimate_minutes=order.cook_estimate_minutes,
                created_at=order.created_at.isoformat(),
                address=address_str,
                lat=lat,
                lng=lng,
                batch_id=batch_id,
                batch_size=(len(batch_order_numbers) or None),
                batch_order_numbers=batch_order_numbers,
                batch_preview=preview.get(order.id),
                order_type=getattr(order, "order_type", None) or "delivery",
                priority=getattr(order, "priority", None) or "normal",
                held_at=order.held_at.isoformat() if getattr(order, "held_at", None) else None,
                held_reason=getattr(order, "held_reason", None),
                table_id=getattr(order, "table_id", None),
                staff_id=getattr(order, "staff_id", None),
                scheduled_for=(
                    order.scheduled_for.isoformat()
                    if getattr(order, "scheduled_for", None)
                    else None
                ),
                is_preorder=bool(getattr(order, "is_preorder", False)),
                customer_allergy_notes=getattr(order, "customer_allergy_notes", None),
                aggregator_source=getattr(order, "aggregator_source", None),
                aggregator_order_ref=getattr(order, "aggregator_order_ref", None),
                source_channel=(
                    getattr(order, "source_channel", None)
                    or getattr(order, "aggregator_source", None)
                ),
                sla_acked_at=(
                    order.sla_acked_at.isoformat()
                    if getattr(order, "sla_acked_at", None)
                    else None
                ),
                sla_acked_by_staff_id=getattr(order, "sla_acked_by_staff_id", None),
            )
        )
    return out


async def _enrich(
    session: AsyncSession, order: Order, *, batch_preview: str | None = None
) -> OrderOut:
    """Join customer, address, items, and rider to produce the full OrderOut."""
    preview = {order.id: batch_preview} if batch_preview else {}
    return (await _enrich_orders_bulk(session, [order], batch_preview=preview))[0]


@router.get("/manual/customer-lookup", response_model=CustomerLookupOut)
async def customer_lookup(
    phone: str,
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
) -> CustomerLookupOut:
    customer = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant.id,
            Customer.phone == phone,
        )
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    last_addr = await get_last_address(session, customer_id=customer.id)
    address_out: AddressOut | None = None
    if last_addr:
        address_out = AddressOut(
            apt_room=last_addr.room_apartment or "",
            building=last_addr.building or "",
            receiver_name=last_addr.receiver_name or "",
            notes=last_addr.additional_details,
        )
    return CustomerLookupOut(name=customer.name, last_address=address_out)


@router.get("/next-token")
async def next_token_endpoint(
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
) -> dict[str, int]:
    """Preview the next daily queue token for this restaurant (today, Asia/Dubai).

    Read-only forecast for the New Order screen — the real token is assigned
    atomically when the order is actually created, so this may skip a number if
    another till places an order first (same as any deli-ticket counter).
    """
    from app.ordering.service import allocate_daily_token

    return {"next_token": await allocate_daily_token(session, restaurant.id)}


@router.post("/manual", response_model=OrderOut)
async def create_manual_order_endpoint(
    body: ManualOrderIn,
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    # Prefer unified POS create when order_type is non-delivery or table-bound;
    # keep legacy create_manual_order path for pure delivery (back-compat).
    from app.ordering.order_types import ORDER_TYPE_DELIVERY
    from app.ordering.pos_orders import create_pos_order

    try:
        if body.order_type != ORDER_TYPE_DELIVERY or body.table_id is not None:
            order = await create_pos_order(
                session,
                restaurant_id=restaurant.id,
                order_type=body.order_type,
                customer_phone=body.customer_phone,
                customer_name=body.customer_name,
                items=[i.model_dump() for i in body.items],
                table_id=body.table_id,
                staff_id=body.staff_id,
                apt_room=body.address.apt_room,
                building=body.address.building,
                receiver_name=body.address.receiver_name,
                address_notes=body.address.notes,
                delivery_fee_aed=body.delivery_fee_aed,
                latitude=body.address.latitude,
                longitude=body.address.longitude,
                scheduled_for=body.scheduled_for,
                is_preorder=body.is_preorder,
                priority=body.priority,
                customer_allergy_notes=body.customer_allergy_notes,
            )
        else:
            order = await create_manual_order(
                session,
                restaurant_id=restaurant.id,
                customer_phone=body.customer_phone,
                customer_name=body.customer_name,
                items=[i.model_dump() for i in body.items],
                apt_room=body.address.apt_room,
                building=body.address.building,
                receiver_name=body.address.receiver_name,
                address_notes=body.address.notes,
                delivery_fee_aed=body.delivery_fee_aed,
                latitude=body.address.latitude,
                longitude=body.address.longitude,
                scheduled_for=body.scheduled_for,
            )
            order.priority = body.priority
            order.is_preorder = body.is_preorder or body.scheduled_for is not None
            if body.customer_allergy_notes:
                order.customer_allergy_notes = body.customer_allergy_notes
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await session.commit()
    from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

    await flush_pending_partner_webhooks(session, restaurant_id=restaurant.id)
    return await _enrich(session, order)


@router.post("/pos", response_model=OrderOut)
async def create_pos_order_endpoint(
    body: PosOrderIn,
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Unified create for dine-in / takeaway / drive-thru / delivery / online / tableside."""
    from app.ordering.pos_orders import create_pos_order

    addr = body.address
    try:
        order = await create_pos_order(
            session,
            restaurant_id=restaurant.id,
            order_type=body.order_type,
            customer_phone=body.customer_phone,
            customer_name=body.customer_name,
            items=[i.model_dump() for i in body.items],
            table_id=body.table_id,
            covers=body.covers,
            staff_id=body.staff_id,
            apt_room=addr.apt_room if addr else None,
            building=addr.building if addr else None,
            receiver_name=addr.receiver_name if addr else None,
            address_notes=addr.notes if addr else None,
            latitude=addr.latitude if addr else None,
            longitude=addr.longitude if addr else None,
            delivery_fee_aed=body.delivery_fee_aed,
            scheduled_for=body.scheduled_for,
            is_preorder=body.is_preorder,
            priority=body.priority,
            customer_allergy_notes=body.customer_allergy_notes,
            auto_confirm=body.auto_confirm,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await session.commit()
    return await _enrich(session, order)


@router.post("/{order_id}/items", response_model=OrderOut)
async def add_items_to_order_endpoint(
    order_id: int,
    body: AddOrderItemsIn,
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Append lines to an open order — the dine-in "another round" flow.

    Spec: order modification is allowed only before the kitchen marks it ready.
    Adds each dish via service.add_item (recomputes subtotal/total), audits, and
    returns the enriched order so the terminal can refresh the running bill.
    """
    from app.menu.models import Dish
    from app.ordering.service import add_item

    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    # Modification window: only before the food is ready / out for delivery.
    ADDABLE_STATUSES = {"draft", "pending_confirmation", "confirmed", "preparing"}
    if str(order.status) not in ADDABLE_STATUSES:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot add items to an order in status {order.status!r}.",
        )

    added: list = []
    for line in body.items:
        dish = await session.get(Dish, line.dish_id)
        if dish is None or dish.restaurant_id != restaurant.id:
            raise HTTPException(
                status_code=422, detail=f"Dish {line.dish_id} not found for this restaurant."
            )
        try:
            item = await add_item(
                session,
                order=order,
                dish=dish,
                qty=line.qty,
                notes=line.notes,
                course_number=line.course_number,
                course_held=line.course_held,
                is_takeaway=line.is_takeaway,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        added.append(item)

    # Cut kitchen tickets for the new lines.
    #
    # add_item() only writes the bill line — station routing, kitchen_status and
    # the print job are stamped by create_tickets_for_items(), which previously
    # ran ONLY on confirm and on fire-course. That meant a second round added to
    # an already-confirmed tab was billed but never appeared on any station
    # board. Only fire for orders the kitchen already owns: a draft still gets
    # its tickets when it is confirmed, and held lines wait for fire-course.
    if str(order.status) not in ("draft", "pending_confirmation"):
        from app.kds.service import create_tickets_for_items

        fireable = [
            i
            for i in added
            if not getattr(i, "course_held", False) and not getattr(i, "cancelled", False)
        ]
        if fireable:
            await create_tickets_for_items(
                session,
                restaurant_id=restaurant.id,
                order=order,
                items=fireable,
            )

    from app.audit.service import record_audit

    await record_audit(
        session,
        actor="cashier",
        restaurant_id=restaurant.id,
        entity="order",
        entity_id=str(order.id),
        action="order_items_added",
        before=None,
        after={"added": [{"dish_id": i.dish_id, "qty": i.qty} for i in body.items]},
    )
    await session.commit()
    return await _enrich(session, order)


@router.post("/{order_id}/confirm", response_model=OrderOut)
async def confirm_order_endpoint(
    order_id: int,
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Fire a parked (draft) order to the kitchen — the waiter's KOT button.

    Waiters build a round with "Save to Table" (POS create with
    auto_confirm=false), which leaves the order DRAFT so the kitchen cannot see
    it yet. This confirms it: starts the SLA, cuts station tickets, deducts
    inventory — everything finalize_confirmation does on an auto-confirmed POS
    sale. Already-confirmed orders are a no-op so a double tap is harmless.
    """
    from app.ordering.service import finalize_confirmation
    from app.tables.models import DiningTable

    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")

    CONFIRMABLE = {"draft", "pending_confirmation"}
    if str(order.status) not in CONFIRMABLE:
        # Idempotent: the ticket is already with the kitchen (or beyond).
        return await _enrich(session, order)

    if not order.items:
        raise HTTPException(status_code=422, detail="Cannot send an empty order.")

    await finalize_confirmation(session, order=order, actor="waiter")

    # A parked dine-in table sits at "seated"; firing it makes it "ordered".
    if order.table_id is not None:
        table = await session.get(DiningTable, order.table_id)
        if table is not None and table.status in ("available", "seated"):
            table.status = "ordered"

    from app.audit.service import record_audit

    await record_audit(
        session,
        actor="waiter",
        restaurant_id=restaurant.id,
        entity="order",
        entity_id=str(order.id),
        action="order_fired_to_kitchen",
        before=None,
        after={"status": str(order.status)},
    )
    await session.commit()
    return await _enrich(session, order)


@router.patch("/{order_id}/covers", response_model=OrderOut)
async def set_order_covers_endpoint(
    order_id: int,
    body: CoversIn,
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Update the dine-in party size on an open tab.

    Covers are captured when the table is opened, but parties grow and shrink.
    Nothing could change them afterwards, so the number went stale and the floor
    plan's cover count with it.
    """
    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    if str(order.status) in ("delivered", "cancelled"):
        raise HTTPException(
            status_code=409, detail="Cannot change covers on a closed order."
        )

    before = getattr(order, "covers", None)
    order.covers = body.covers

    from app.audit.service import record_audit

    await record_audit(
        session,
        actor="waiter",
        restaurant_id=restaurant.id,
        entity="order",
        entity_id=str(order.id),
        action="covers_changed",
        before={"covers": before},
        after={"covers": body.covers},
    )
    await session.commit()
    return await _enrich(session, order)


@router.post("/repeat-last", response_model=OrderOut)
async def repeat_last_order_endpoint(
    body: RepeatLastOrderIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    from app.ordering.pos_orders import repeat_last_order

    try:
        order = await repeat_last_order(
            session,
            restaurant_id=restaurant.id,
            customer_phone=body.customer_phone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await session.commit()
    return await _enrich(session, order)


@router.post("/release-scheduled")
async def release_scheduled_endpoint(
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Release due scheduled/pre-orders to kitchen for this restaurant."""
    from app.ordering.scheduled import release_due_scheduled_orders

    released = await release_due_scheduled_orders(session, restaurant_id=restaurant.id)
    await session.commit()
    return {
        "released_count": len(released),
        "order_ids": [o.id for o in released],
        "order_numbers": [o.order_number for o in released],
    }


@router.post("/{order_id}/hold", response_model=OrderOut)
async def hold_order_endpoint(
    order_id: int,
    body: HoldOrderIn | None = None,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    from app.ordering.pos_orders import hold_order

    try:
        order = await hold_order(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            reason=body.reason if body else None,
        )
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=404 if msg == "Order not found" else 422, detail=msg)
    await session.commit()
    return await _enrich(session, order)


@router.post("/{order_id}/unhold", response_model=OrderOut)
async def unhold_order_endpoint(
    order_id: int,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    from app.ordering.pos_orders import unhold_order

    try:
        order = await unhold_order(
            session, restaurant_id=restaurant.id, order_id=order_id
        )
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=404 if msg == "Order not found" else 422, detail=msg)
    await session.commit()
    return await _enrich(session, order)


@router.patch("/{order_id}/priority", response_model=OrderOut)
async def set_priority_endpoint(
    order_id: int,
    body: PriorityIn,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    from app.ordering.pos_orders import set_order_priority

    try:
        order = await set_order_priority(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            priority=body.priority,
        )
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=404 if msg == "Order not found" else 422, detail=msg)
    await session.commit()
    return await _enrich(session, order)


@router.post("/{order_id}/rush", response_model=OrderOut)
async def rush_order_endpoint(
    order_id: int,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    from app.ordering.pos_orders import mark_rush

    try:
        order = await mark_rush(
            session, restaurant_id=restaurant.id, order_id=order_id
        )
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=404 if msg == "Order not found" else 422, detail=msg)
    await session.commit()
    return await _enrich(session, order)


@router.post("/{order_id}/fire-course", response_model=OrderOut)
async def fire_course_endpoint(
    order_id: int,
    body: FireCourseIn,
    # Floor staff release held courses — it is the other half of holding a line.
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "waiter")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    from app.ordering.pos_orders import fire_course

    try:
        await fire_course(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            course_number=body.course_number,
        )
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=404 if msg == "Order not found" else 422, detail=msg)
    await session.commit()
    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    return await _enrich(session, order)


@router.post("/{order_id}/refund-order")
async def refund_order_endpoint(
    order_id: int,
    body: RefundOrderIn | None = None,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Full remaining refund across all succeeded payments on the order."""
    from app.ordering.pos_orders import refund_order

    try:
        result = await refund_order(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            reason=body.reason if body else None,
        )
    except ValueError as exc:
        msg = str(exc)
        raise HTTPException(status_code=404 if msg == "Order not found" else 422, detail=msg)
    await session.commit()
    return result


@router.post("/merge", response_model=OrderOut)
async def merge_orders_endpoint(
    body: MergeOrdersIn,
    restaurant: Restaurant = Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Merge all items from ``secondary_order_id`` onto ``primary_order_id`` and
    cancel the now-empty secondary. 404 if either order doesn't exist for this
    tenant; 422 if either isn't in a mergeable (pre-'ready') status."""
    try:
        order = await merge_orders(
            session,
            restaurant_id=restaurant.id,
            primary_order_id=body.primary_order_id,
            secondary_order_id=body.secondary_order_id,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if msg == "Order not found" else 422
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    await session.refresh(order)
    return await _enrich(session, order)


@router.post("/{order_id}/unmerge", response_model=OrderOut)
async def unmerge_last_endpoint(
    order_id: int,
    restaurant: Restaurant = Depends(require_role("manager", "cashier")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Undo the most recent table merge into this order — the last-merged table's
    bill pops back onto its own table. 409 if there's nothing to un-merge."""
    from app.ordering.service import unmerge_last_merge

    try:
        revived = await unmerge_last_merge(
            session, restaurant_id=restaurant.id, primary_order_id=order_id
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if msg == "Order not found" else 409
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    await session.refresh(revived)
    return await _enrich(session, revived)


@router.post("/{order_id}/advance", response_model=OrderOut)
async def advance_order(
    order_id: int,
    # KOT is a cashier action (confirmed -> preparing) and the kitchen advances
    # preparing -> ready, so both roles need this alongside the manager/owner.
    restaurant: Restaurant = Depends(require_role("manager", "cashier", "kitchen")),
    # Attribute the FSM hop to whoever pressed it, so the order timeline reads
    # "by cashier" / "by kitchen" / "by manager" instead of a blanket "manager".
    actor: str = Depends(current_actor),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        order = await advance_kitchen_status(session, order=order, actor=actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    # Deliver the customer status ping ("started preparing" / "ready") NOW, in this
    # request — otherwise it sits in the outbox until the slow background poll, which
    # made the customer get "preparing" many minutes after the kitchen tapped it.
    from app.outbox.service import deliver_pending

    await deliver_pending(session, restaurant.id)
    return await _enrich(session, order)


@router.post("/{order_id}/duplicate")
async def duplicate_order_endpoint(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Repeat/duplicate an existing order (any status) into a fresh draft."""
    from app.ordering.duplicate import duplicate_order

    try:
        new_order = await duplicate_order(session, restaurant_id=restaurant.id, order_id=order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await session.commit()
    return {
        "id": new_order.id,
        "order_number": new_order.order_number,
        "status": new_order.status,
        "total_aed": str(new_order.total),
    }


@router.post("/{order_id}/sla-ack", response_model=OrderOut)
async def acknowledge_sla_endpoint(
    order_id: int,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Acknowledge a late order's SLA alert so it leaves the Live Ops queue.

    Manager-gated on purpose: silencing a breach alert is an accountability
    action, so it is recorded in the audit trail with who did it. It does NOT
    change the order's status or stop the SLA clock — the order is still late.
    Idempotent; re-acknowledging keeps the first acknowledgement.
    """
    try:
        await acknowledge_sla_breach(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            actor="manager",
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await session.commit()
    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return (await _enrich_orders_bulk(session, [order]))[0]


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel_order_endpoint(
    order_id: int,
    body: CancelOrderIn | None = None,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Cancel/void an order — manager approval required (restaurant owner token
    always passes; a staff token must carry the "manager" role). Legal through
    ``arriving`` — any active pre-delivery status. Restaurant cancellation never
    resells the food (assumed unavailable/unfit) — resale only happens on a
    CUSTOMER cancel of a cooking order. ``delivered`` and terminal states return 422."""
    from app.staff.approvals import create_approval_request, raise_suspicious
    from app.staff.mistakes import record_mistake

    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        await cancel_order(
            session,
            order=order,
            actor="manager",
            reason=(body.reason if body else None),
        )
    except IllegalTransitionError:
        raise HTTPException(
            status_code=422,
            detail=f"Order in status '{order.status}' can no longer be cancelled.",
        )
    # Category 9 — void approval trail + optional mistake attribution
    await create_approval_request(
        session,
        restaurant_id=restaurant.id,
        action_type="void",
        order_id=order_id,
        amount_aed=order.total,
        reason=(body.reason if body else None),
        status="approved",
        payload={"order_number": order.order_number, "status_before_cancel": "voided"},
    )
    if order.staff_id is not None:
        await record_mistake(
            session,
            restaurant_id=restaurant.id,
            staff_id=order.staff_id,
            mistake_type="void",
            order_id=order_id,
            amount_aed=order.total,
            notes=(body.reason if body else None),
        )
        await raise_suspicious(
            session,
            restaurant_id=restaurant.id,
            alert_type="order_voided",
            severity="medium",
            staff_id=order.staff_id,
            detail={"order_id": order_id, "total": str(order.total)},
        )
    await session.commit()
    # Flush cancellation customer ping + partner webhook now, not on background poll.
    from app.outbox.service import deliver_pending
    from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

    await deliver_pending(session, restaurant.id)
    await flush_pending_partner_webhooks(session, restaurant_id=restaurant.id)
    await session.refresh(order)
    return await _enrich(session, order)


def _item_mutation_status_code(msg: str) -> int:
    return 404 if msg in ("Order not found", "Order item not found") else 422


@router.post("/{order_id}/items/{item_id}/cancel", response_model=OrderOut)
async def cancel_order_item_endpoint(
    order_id: int,
    item_id: int,
    body: CancelOrderItemIn | None = None,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Cancel a single line item without voiding the whole order — manager approval
    required. Legal only before the order reaches 'ready' (same gate as order
    modification). 404 if the order/item doesn't exist for this tenant, 422 if the
    order has passed the modifiable window or the item is already cancelled."""
    try:
        await cancel_order_item(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            order_item_id=item_id,
            reason=(body.reason if body else None),
            actor="manager",
        )
    except ValueError as exc:
        raise HTTPException(status_code=_item_mutation_status_code(str(exc)), detail=str(exc))
    await session.commit()
    order = await get_order_for_tenant(session, restaurant_id=restaurant.id, order_id=order_id)
    return await _enrich(session, order)


@router.patch("/{order_id}/items/{item_id}", response_model=OrderOut)
async def edit_order_item_endpoint(
    order_id: int,
    item_id: int,
    body: EditOrderItemIn,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Edit qty and/or notes on an unfired line item — manager approval required.
    Legal only before the order reaches 'ready' (same gate as order modification).
    404 if the order/item doesn't exist for this tenant, 422 if the order has passed
    the modifiable window or the requested qty is invalid."""
    try:
        await edit_order_item(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            order_item_id=item_id,
            new_qty=body.qty,
            new_notes=body.notes,
            actor="manager",
        )
    except ValueError as exc:
        raise HTTPException(status_code=_item_mutation_status_code(str(exc)), detail=str(exc))
    await session.commit()
    order = await get_order_for_tenant(session, restaurant_id=restaurant.id, order_id=order_id)
    return await _enrich(session, order)


@router.post("/{order_id}/split-by-items", response_model=OrderOut)
async def split_order_by_items_endpoint(
    order_id: int,
    body: SplitOrderByItemsIn,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Split the given line items off onto a new draft order (same customer/table)
    — manager approval required. Returns the NEW split-off order. 404 if the source
    order doesn't exist for this tenant; 422 if past the modifiable window or any
    item_id doesn't belong to this order."""
    try:
        new_order = await split_order_by_items(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            item_ids=body.item_ids,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if msg == "Order not found" else 422
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    await session.refresh(new_order)
    return await _enrich(session, new_order)


@router.post("/{order_id}/split-by-seat", response_model=OrderOut)
async def split_order_by_seat_endpoint(
    order_id: int,
    body: SplitOrderBySeatIn,
    restaurant: Restaurant = Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Split every item assigned to ``seat_number`` off onto a new draft order —
    manager approval required. Returns the NEW split-off order. 404 if the source
    order doesn't exist for this tenant; 422 if past the modifiable window or no
    items carry that seat number."""
    try:
        new_order = await split_order_by_seat(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            seat_number=body.seat_number,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if msg == "Order not found" else 422
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    await session.refresh(new_order)
    return await _enrich(session, new_order)


@router.patch("/{order_id}/transfer-staff", response_model=OrderOut)
async def transfer_order_staff_endpoint(
    order_id: int,
    body: TransferOrderStaffIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Reassign sales-per-server attribution to another staff member of this
    tenant. 404 if the order or staff member doesn't exist for this tenant."""
    try:
        order = await transfer_order_staff(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            new_staff_id=body.staff_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    await session.commit()
    await session.refresh(order)
    return await _enrich(session, order)


@router.post("/{order_id}/reassign", response_model=OrderOut)
async def reassign_order_endpoint(
    order_id: int,
    body: ReassignOrderIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Manually reassign an ASSIGNED order to a chosen rider (recovery path when
    the original rider is stuck/unreachable). Frees the old rider and notifies
    the new one. 422 if the order isn't assignable or the rider is invalid."""
    from app.dispatch.service import reassign_order

    try:
        order = await reassign_order(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            new_rider_id=body.rider_id,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if msg in ("Order not found", "Rider not found") else 422
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    # Flush the rider notification now — this handler has no event-driven
    # delivery of its own, so without this the message sits pending forever.
    from app.outbox.service import deliver_pending

    await deliver_pending(session, restaurant.id)
    await session.refresh(order)
    return await _enrich(session, order)


@router.post("/{order_id}/assign", response_model=OrderOut)
async def assign_order_endpoint(
    order_id: int,
    body: ReassignOrderIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Manually assign an unassigned ready/preparing order to a chosen rider."""
    from app.dispatch.service import assign_order

    try:
        order = await assign_order(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            rider_id=body.rider_id,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if msg in ("Order not found", "Rider not found") else 422
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    from app.outbox.service import deliver_pending

    await deliver_pending(session, restaurant.id)
    await session.refresh(order)
    return await _enrich(session, order)


@router.post("/{order_id}/delivery-photo", response_model=OrderOut)
async def set_delivery_photo_endpoint(
    order_id: int,
    body: DeliveryPhotoIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Attach a rider proof-of-delivery photo URL to an in-flight order.

    Legal any time from rider-assignment up to (not including) delivered —
    same status set the delivery FSM itself allows forward transitions from.
    """
    from app.dispatch.delivery_proof import DeliveryPhotoError, set_delivery_photo

    try:
        order = await set_delivery_photo(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            photo_url=body.photo_url,
            photo_base64=body.photo_base64,
        )
    except DeliveryPhotoError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg else 422
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    await session.refresh(order)
    return await _enrich(session, order)


@router.post("/{order_id}/verify-delivery-otp")
async def verify_delivery_otp_endpoint(
    order_id: int,
    body: VerifyDeliveryOtpIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Check a customer-provided OTP against the code texted at hand-off time.

    Informational only — it does not gate or advance the delivery FSM.
    """
    from app.dispatch.delivery_proof import OtpVerificationError, verify_delivery_otp

    try:
        verified = await verify_delivery_otp(
            session, restaurant_id=restaurant.id, order_id=order_id, otp=body.otp
        )
    except OtpVerificationError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg else 422
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    return {"verified": verified}


@router.post("/{order_id}/delivery-failed", response_model=OrderOut)
async def mark_delivery_failed_endpoint(
    order_id: int,
    body: DeliveryFailedIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Record why a delivery attempt failed and move the order to the FSM's
    existing ``undeliverable`` status. Legal only from ``picked_up`` / ``arriving``
    (whatever the FSM already allows into ``undeliverable``) — 422 otherwise."""
    from app.dispatch.delivery import mark_delivery_failed

    try:
        order = await mark_delivery_failed(
            session, restaurant_id=restaurant.id, order_id=order_id, reason=body.reason
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg else 422
        raise HTTPException(status_code=code, detail=msg)
    await session.commit()
    await session.refresh(order)
    return await _enrich(session, order)


@router.delete("/{order_id}", status_code=204)
async def delete_order_endpoint(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Hard-delete an order and its dependents (admin/test-data cleanup).
    Tenant-scoped + destructive — for clearing test orders, not customer-facing
    cancellation (use /cancel for that)."""
    deleted = await delete_order(session, restaurant_id=restaurant.id, order_id=order_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Order not found")


@router.get("/{order_id}/detail", response_model=OrderDetailOut)
async def get_order_detail_endpoint(
    order_id: int,
    include: str | None = Query(default="overview"),
    restaurant: Restaurant = Depends(current_restaurant_any),
    session: AsyncSession = Depends(get_session),
) -> OrderDetailOut:
    try:
        return await get_order_detail(
            session,
            restaurant_id=restaurant.id,
            order_id=order_id,
            includes=parse_detail_includes(include),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{order_id}/tax-invoice")
async def get_tax_invoice(
    order_id: int,
    document_type: str | None = None,
    buyer_trn: str | None = None,
    buyer_name: str | None = None,
    restaurant: Restaurant = Depends(current_restaurant_any),
    session: AsyncSession = Depends(get_session),
):
    from app.ordering.tax import build_tax_invoice

    try:
        return await build_tax_invoice(
            session,
            order_id=order_id,
            restaurant_id=restaurant.id,
            document_type=document_type,
            buyer_trn=buyer_trn,
            buyer_name=buyer_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant_any),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return await _enrich(session, order)


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    from_date: str | None = None,
    to_date: str | None = None,
    q: str | None = None,
    updated_since: datetime | None = Query(default=None),
    preview_batch: bool = Query(default=True),
    scheduled_only: bool = Query(default=False),
    open_only: bool = Query(default=False),
    held_only: bool = Query(default=False),
    order_type: str | None = Query(default=None),
    channel: str | None = Query(default=None, description="source_channel / aggregator filter"),
    exclude_channel: str | None = Query(
        default=None,
        description="drop rows with this source_channel (e.g. 'pos' so the WhatsApp "
        "queue excludes cashier-entered Home Delivery orders)",
    ),
    restaurant: Restaurant = Depends(current_restaurant_any),
    session: AsyncSession = Depends(get_session),
) -> list[OrderOut]:
    orders = await list_orders_for_tenant(
        session,
        restaurant_id=restaurant.id,
        status=status,
        limit=limit,
        offset=offset,
        from_date=from_date,
        to_date=to_date,
        q=q,
        updated_since=updated_since,
        scheduled_only=scheduled_only,
        open_only=open_only,
        held_only=held_only,
        order_type=order_type,
        channel=channel,
        exclude_channel=exclude_channel,
    )
    preview: dict[int, str] = {}
    if preview_batch:
        # Forecast which still-unassigned orders will batch together, so the list can
        # flag it before a rider is assigned.
        from app.dispatch.service import preview_batch_groups

        preview = await preview_batch_groups(session, restaurant_id=restaurant.id)
    return await _enrich_orders_bulk(session, orders, batch_preview=preview)


@router.post("/{order_id}/nps", response_model=NpsResponseOut, status_code=201)
async def submit_nps_response(
    order_id: int,
    body: NpsResponseIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> NpsResponseOut:
    """Post-delivery NPS survey response (0-10) tied to a tenant order."""
    from app.loyalty import nps as nps_service

    order = await get_order_for_tenant(session, restaurant_id=restaurant.id, order_id=order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        resp = await nps_service.record_nps_response(
            session, restaurant_id=restaurant.id, customer_id=body.customer_id,
            order_id=order_id, score=body.score, comment=body.comment,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await session.commit()
    return NpsResponseOut(
        id=resp.id, order_id=resp.order_id, customer_id=resp.customer_id,
        score=resp.score, comment=resp.comment, created_at=resp.created_at,
    )


