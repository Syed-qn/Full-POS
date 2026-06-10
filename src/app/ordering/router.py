# src/app/ordering/router.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant, Rider
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.ordering.schemas import AddressOut, CustomerLookupOut, ManualOrderIn, OrderItemOut, OrderOut
from app.ordering.detail_schemas import (
    OrderDetailOut,
)
from app.ordering.service import (
    advance_kitchen_status,
    create_manual_order,
    get_last_address,
    get_order_detail,
    get_order_for_tenant,
    list_orders_for_tenant,
)

router = APIRouter(prefix="/api/v1/orders", tags=["orders"])


async def _enrich(session: AsyncSession, order: Order) -> OrderOut:
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

    sla_started_at = (
        order.sla_confirmed_at.isoformat() if order.sla_confirmed_at else None
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
        created_at=order.created_at.isoformat(),
        address=address_str,
        lat=lat,
        lng=lng,
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
    return [await _enrich(session, o) for o in orders]


