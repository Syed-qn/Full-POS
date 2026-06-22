# src/app/ordering/customer_router.py
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.marketing.models import OptOut
from app.marketing.optout import is_opted_out
from app.ordering.detail_schemas import (
    AddressDetailOut,
    AddressPatchIn,
    CustomerDetailOut,
    CustomerListOut,
    CustomerPatchIn,
    CustomerProfileOut,
    OrderSummaryOut,
)
from app.ordering.models import Customer, CustomerAddress, Order
from app.ordering.service import compute_usual_order_time, patch_address, patch_customer

router = APIRouter(prefix="/api/v1/ordering/customers", tags=["customers"])

_OPEN_STATUSES = frozenset(
    {"draft", "pending_confirmation", "confirmed", "preparing", "ready", "assigned", "picked_up", "arriving", "on_resale"}
)


@router.get("", response_model=CustomerListOut)
async def list_customers(
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> CustomerListOut:
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

    if rows:
        phones = [c.phone for c in rows]
        opted_out_phones = set(
            (await session.scalars(
                select(OptOut.phone).where(
                    OptOut.restaurant_id == restaurant.id,
                    OptOut.phone.in_(phones),
                )
            )).all()
        )
    else:
        opted_out_phones = set()

    # The WhatsApp flow only ever collects a receiver name, so customers can
    # have no name on file. Fall back to their most recent address receiver
    # (bulk query, newest first) so the Name column isn't blank.
    nameless_ids = [c.id for c in rows if not (c.name or "").strip()]
    receiver_by_customer: dict[int, str] = {}
    if nameless_ids:
        addr_rows = (await session.scalars(
            select(CustomerAddress)
            .where(
                CustomerAddress.customer_id.in_(nameless_ids),
                CustomerAddress.receiver_name.isnot(None),
            )
            .order_by(CustomerAddress.id.desc())
        )).all()
        for a in addr_rows:
            rn = (a.receiver_name or "").strip()
            if rn and a.customer_id not in receiver_by_customer:
                receiver_by_customer[a.customer_id] = rn

    items = [
        CustomerDetailOut(
            id=c.id,
            name=c.name or receiver_by_customer.get(c.id),
            phone=c.phone,
            total_orders=c.total_orders,
            total_spend=c.total_spend,
            first_order_at=c.first_order_at,
            last_order_at=c.last_order_at,
            marketing_opted_in=c.phone not in opted_out_phones,
        )
        for c in rows
    ]
    return CustomerListOut(items=items, limit=limit, offset=offset)


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
    usual_order_time = await compute_usual_order_time(session, customer.id)

    # Fall back to the most recent address receiver when no name is on file.
    profile_name = customer.name
    if not (profile_name or "").strip():
        for a in sorted(addresses_rows, key=lambda x: x.id, reverse=True):
            if (a.receiver_name or "").strip():
                profile_name = a.receiver_name.strip()
                break

    return CustomerProfileOut(
        id=customer.id,
        name=profile_name,
        phone=customer.phone,
        total_orders=customer.total_orders,
        total_spend=customer.total_spend,
        first_order_at=customer.first_order_at,
        last_order_at=customer.last_order_at,
        usual_order_time=usual_order_time,
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
            Order.restaurant_id == restaurant.id,
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


@router.delete("/{customer_id}", status_code=204)
async def delete_customer(
    customer_id: int,
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

    has_orders = await session.scalar(
        select(Order.id).where(
            Order.customer_id == customer_id,
            Order.restaurant_id == restaurant.id,
        ).limit(1)
    )
    if has_orders:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete customer linked to existing orders",
        )

    await session.execute(
        delete(CustomerAddress).where(CustomerAddress.customer_id == customer_id)
    )
    await session.execute(
        delete(OptOut).where(
            OptOut.restaurant_id == restaurant.id,
            OptOut.phone == customer.phone,
        )
    )
    from app.marketing.models import MarketingSend

    await session.execute(
        delete(MarketingSend).where(MarketingSend.customer_id == customer_id)
    )
    await session.delete(customer)
    await session.commit()
    return Response(status_code=204)
