# src/app/ordering/customer_router.py
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.marketing.optout import is_opted_out
from app.ordering.detail_schemas import (
    AddressDetailOut,
    AddressPatchIn,
    CustomerDetailOut,
    CustomerPatchIn,
    CustomerProfileOut,
    OrderSummaryOut,
)
from app.ordering.models import Customer, CustomerAddress, Order
from app.ordering.service import patch_address, patch_customer

router = APIRouter(prefix="/api/v1/ordering/customers", tags=["customers"])

_OPEN_STATUSES = frozenset(
    {"draft", "pending_confirmation", "confirmed", "preparing", "ready", "assigned", "picked_up", "arriving"}
)


@router.get("", response_model=dict)
async def list_customers(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    stmt = select(Customer).where(Customer.restaurant_id == restaurant.id)
    if q:
        pattern = f"%{q}%"
        stmt = stmt.where(
            or_(
                Customer.phone.ilike(pattern),
                Customer.name.ilike(pattern),
            )
        )
    rows = list(
        (await session.scalars(stmt.order_by(Customer.id.desc()).limit(limit).offset(offset))).all()
    )
    items = []
    for c in rows:
        opted_out = await is_opted_out(session, restaurant_id=restaurant.id, phone=c.phone)
        items.append(CustomerDetailOut(
            id=c.id,
            name=c.name,
            phone=c.phone,
            total_orders=c.total_orders,
            total_spend=c.total_spend,
            first_order_at=c.first_order_at,
            last_order_at=c.last_order_at,
            marketing_opted_in=not opted_out,
        ).model_dump())
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/{customer_id}", response_model=CustomerProfileOut)
async def get_customer_profile(
    customer_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CustomerProfileOut:
    customer = await session.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant.id,
        )
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    addresses_rows = list(
        (await session.scalars(
            select(CustomerAddress).where(CustomerAddress.customer_id == customer.id)
        )).all()
    )

    recent_orders_rows = list(
        (await session.scalars(
            select(Order)
            .where(Order.customer_id == customer.id, Order.restaurant_id == restaurant.id)
            .order_by(Order.created_at.desc())
            .limit(10)
        )).all()
    )

    opted_out = await is_opted_out(session, restaurant_id=restaurant.id, phone=customer.phone)

    return CustomerProfileOut(
        id=customer.id,
        name=customer.name,
        phone=customer.phone,
        total_orders=customer.total_orders,
        total_spend=customer.total_spend,
        first_order_at=customer.first_order_at,
        last_order_at=customer.last_order_at,
        marketing_opted_in=not opted_out,
        tags=customer.tags if customer.tags is not None else {},
        addresses=[
            AddressDetailOut(
                id=a.id,
                room_apartment=a.room_apartment,
                building=a.building,
                receiver_name=a.receiver_name,
                additional_details=a.additional_details,
                latitude=a.latitude,
                longitude=a.longitude,
            )
            for a in addresses_rows
        ],
        recent_orders=[
            OrderSummaryOut(
                id=o.id,
                order_number=o.order_number,
                status=o.status,
                total=o.total,
                created_at=o.created_at,
            )
            for o in recent_orders_rows
        ],
    )


@router.patch("/{customer_id}", response_model=CustomerDetailOut)
async def patch_customer_endpoint(
    customer_id: int,
    body: CustomerPatchIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CustomerDetailOut:
    try:
        customer = await patch_customer(
            session,
            restaurant_id=restaurant.id,
            customer_id=customer_id,
            name=body.name,
            phone=body.phone,
            marketing_opted_in=body.marketing_opted_in,
        )
        await session.commit()
        opted_out = await is_opted_out(session, restaurant_id=restaurant.id, phone=customer.phone)
        return CustomerDetailOut(
            id=customer.id,
            name=customer.name,
            phone=customer.phone,
            total_orders=customer.total_orders,
            total_spend=customer.total_spend,
            first_order_at=customer.first_order_at,
            last_order_at=customer.last_order_at,
            marketing_opted_in=not opted_out,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.patch("/{customer_id}/addresses/{address_id}", response_model=AddressDetailOut)
async def patch_address_endpoint(
    customer_id: int,
    address_id: int,
    body: AddressPatchIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> AddressDetailOut:
    try:
        addr = await patch_address(
            session,
            restaurant_id=restaurant.id,
            customer_id=customer_id,
            address_id=address_id,
            room_apartment=body.room_apartment,
            building=body.building,
            receiver_name=body.receiver_name,
            additional_details=body.additional_details,
        )
        await session.commit()
        return AddressDetailOut(
            id=addr.id,
            room_apartment=addr.room_apartment,
            building=addr.building,
            receiver_name=addr.receiver_name,
            additional_details=addr.additional_details,
            latitude=addr.latitude,
            longitude=addr.longitude,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{customer_id}/addresses/{address_id}", status_code=204)
async def delete_address(
    customer_id: int,
    address_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> Response:
    customer = await session.scalar(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant.id,
        )
    )
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    addr = await session.scalar(
        select(CustomerAddress).where(
            CustomerAddress.id == address_id,
            CustomerAddress.customer_id == customer_id,
        )
    )
    if not addr:
        raise HTTPException(status_code=404, detail="Address not found")

    open_order = await session.scalar(
        select(Order).where(
            Order.address_id == address_id,
            Order.status.in_(_OPEN_STATUSES),
        )
    )
    if open_order:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete address linked to an open order",
        )

    await session.delete(addr)
    await session.commit()
    return Response(status_code=204)
