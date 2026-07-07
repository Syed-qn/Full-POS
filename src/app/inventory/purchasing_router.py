from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.inventory.models import PurchaseOrder, PurchaseOrderLine, Vendor
from app.inventory.purchasing import create_purchase_order, create_vendor, receive_purchase_order
from app.inventory.schemas import PurchaseOrderIn, PurchaseOrderOut, VendorIn, VendorOut

router = APIRouter(tags=["inventory"])


async def _load_po_out(session: AsyncSession, po: PurchaseOrder) -> PurchaseOrder:
    lines = (await session.scalars(
        select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)
    )).all()
    po.lines = list(lines)  # attach for response_model serialization
    return po


@router.post("/api/v1/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
async def create_vendor_endpoint(
    body: VendorIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    vendor = await create_vendor(
        session, restaurant_id=restaurant.id, name=body.name, phone=body.phone, email=body.email,
    )
    await session.commit()
    await session.refresh(vendor)
    return vendor


@router.post("/api/v1/purchase-orders", response_model=PurchaseOrderOut, status_code=status.HTTP_201_CREATED)
async def create_purchase_order_endpoint(
    body: PurchaseOrderIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    vendor = await session.get(Vendor, body.vendor_id)
    if vendor is None or vendor.restaurant_id != restaurant.id:
        raise HTTPException(status_code=404, detail="vendor not found")

    po = await create_purchase_order(
        session, restaurant_id=restaurant.id, vendor_id=body.vendor_id,
        lines=[line.model_dump() for line in body.lines],
    )
    await session.commit()
    await session.refresh(po)
    return await _load_po_out(session, po)


@router.post("/api/v1/purchase-orders/{po_id}/receive", response_model=PurchaseOrderOut)
async def receive_purchase_order_endpoint(
    po_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        po = await receive_purchase_order(session, restaurant_id=restaurant.id, po_id=po_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="purchase order not found")
    await session.commit()
    await session.refresh(po)
    return await _load_po_out(session, po)
