# src/app/ordering/router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant, Rider
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
)

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


async def _enrich(
    session: AsyncSession, order: Order, *, batch_preview: str | None = None
) -> OrderOut:
    """Join customer, address, items, and rider to produce the full OrderOut."""
    customer = await session.get(Customer, order.customer_id)
    customer_name = getattr(customer, "name", None)
    customer_phone = customer.phone if customer else ""

    items_rows = list(
        (
            await session.scalars(
                select(OrderItem).where(OrderItem.order_id == order.id)
            )
        ).all()
    )
    items = [
        OrderItemOut(
            dish_number=i.dish_number,
            name=i.dish_name,
            qty=i.qty,
            price_aed=str(i.price_aed),
        )
        for i in items_rows
    ]

    rider_name: str | None = None
    if order.rider_id is not None:
        rider = await session.get(Rider, order.rider_id)
        rider_name = rider.name if rider else None

    address_str: str | None = None
    lat: float | None = None
    lng: float | None = None
    if order.address_id is not None:
        addr = await session.get(CustomerAddress, order.address_id)
        if addr:
            parts = [p for p in [addr.room_apartment, addr.building] if p]
            address_str = ", ".join(parts) or None
            lat = addr.latitude
            lng = addr.longitude
            # Fall back to the delivery receiver name when the customer has no
            # name on file (older orders predating the name backfill).
            if not (customer_name or "").strip() and addr.receiver_name:
                customer_name = addr.receiver_name

    # Still nameless (e.g. a draft with no address yet)? Use the customer's most
    # recent receiver name from any of their past orders.
    if customer is not None and not (customer_name or "").strip():
        customer_name = await session.scalar(
            select(CustomerAddress.receiver_name)
            .where(
                CustomerAddress.customer_id == customer.id,
                CustomerAddress.receiver_name.isnot(None),
            )
            .order_by(CustomerAddress.id.desc())
            .limit(1)
        )

    sla_started_at = (
        order.sla_confirmed_at.isoformat() if order.sla_confirmed_at else None
    )

    # Batching: if this order is part of a rider trip, list every order on that trip
    # (in delivery sequence) so the dashboard can flag matched orders.
    from app.dispatch.models import BatchOrder

    batch_id: int | None = None
    batch_order_numbers: list[str] = []
    bo = await session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == order.id)
    )
    if bo is not None:
        batch_id = bo.batch_id
        batch_order_numbers = list(
            (
                await session.execute(
                    select(Order.order_number)
                    .join(BatchOrder, BatchOrder.order_id == Order.id)
                    .where(BatchOrder.batch_id == bo.batch_id)
                    .order_by(BatchOrder.sequence)
                )
            ).scalars().all()
        )

    return OrderOut(
        id=order.id,
        order_number=order.order_number,
        status=str(order.status),
        customer_name=customer_name,
        customer_phone=customer_phone,
        items=items,
        total_aed=str(order.total),
        rider_id=order.rider_id,
        rider_name=rider_name,
        sla_started_at=sla_started_at,
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
        batch_preview=batch_preview,
    )


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
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await session.commit()
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
    return await _enrich(session, order)


@router.post("/{order_id}/cancel", response_model=OrderOut)
async def cancel_order_endpoint(
    order_id: int,
    body: CancelOrderIn | None = None,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderOut:
    """Cancel an order. Legal before delivery only: draft/pending/confirmed →
    cancelled; preparing → on_resale (food already cooked, auto-resold per spec).
    Later states (ready/assigned/picked_up/arriving/terminal) return 422."""
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
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> OrderDetailOut:
    try:
        return await get_order_detail(session, restaurant_id=restaurant.id, order_id=order_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


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
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[OrderOut]:
    orders = await list_orders_for_tenant(
        session, restaurant_id=restaurant.id, status=status, limit=limit
    )
    # Forecast which still-unassigned orders will batch together, so the list can
    # flag it before a rider is assigned.
    from app.dispatch.service import preview_batch_groups

    preview = await preview_batch_groups(session, restaurant_id=restaurant.id)
    return [await _enrich(session, o, batch_preview=preview.get(o.id)) for o in orders]


