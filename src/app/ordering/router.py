# src/app/ordering/router.py
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant, Rider
from app.staff.deps import require_role
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.ordering.schemas import (
    AddressOut,
    CancelOrderIn,
    CustomerLookupOut,
    ManualOrderIn,
    OrderItemOut,
    OrderOut,
    ReassignOrderIn,
)
from app.ordering.detail_schemas import (
    OrderDetailOut,
)
from app.ordering.fsm import IllegalTransitionError
from app.ordering.service import (
    advance_kitchen_status,
    cancel_order,
    create_manual_order,
    delete_order,
    get_last_address,
    get_order_detail,
    get_order_for_tenant,
    list_orders_for_tenant,
    parse_detail_includes,
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
                resale_of_order_id=order.resale_of_order_id,
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
    restaurant: Restaurant = Depends(current_restaurant),
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


@router.post("/manual", response_model=OrderOut)
async def create_manual_order_endpoint(
    body: ManualOrderIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    try:
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
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await session.commit()
    from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

    await flush_pending_partner_webhooks(session, restaurant_id=restaurant.id)
    return await _enrich(session, order)


@router.post("/{order_id}/advance", response_model=OrderOut)
async def advance_order(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    order = await get_order_for_tenant(
        session, restaurant_id=restaurant.id, order_id=order_id
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    try:
        order = await advance_kitchen_status(session, order=order)
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
    await session.commit()
    # Flush cancellation customer ping + partner webhook now, not on background poll.
    from app.outbox.service import deliver_pending
    from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

    await deliver_pending(session, restaurant.id)
    await flush_pending_partner_webhooks(session, restaurant_id=restaurant.id)
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
    restaurant: Restaurant = Depends(current_restaurant),
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
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    from app.ordering.tax import build_tax_invoice

    try:
        return await build_tax_invoice(session, order_id=order_id, restaurant_id=restaurant.id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(
    order_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
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
    restaurant: Restaurant = Depends(current_restaurant),
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
    )
    preview: dict[int, str] = {}
    if preview_batch:
        # Forecast which still-unassigned orders will batch together, so the list can
        # flag it before a rider is assigned.
        from app.dispatch.service import preview_batch_groups

        preview = await preview_batch_groups(session, restaurant_id=restaurant.id)
    return await _enrich_orders_bulk(session, orders, batch_preview=preview)


