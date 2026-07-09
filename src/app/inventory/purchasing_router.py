from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.inventory.models import PurchaseOrder, PurchaseOrderLine
from app.inventory.purchasing import (
    create_grn,
    create_purchase_order,
    create_vendor,
    list_grns,
    list_purchase_orders,
    list_vendors,
    receive_purchase_order,
    update_vendor,
)
from app.inventory.schemas import (
    GrnIn,
    GrnOut,
    PurchaseOrderIn,
    PurchaseOrderOut,
    VendorIn,
    VendorOut,
    VendorPatch,
)

router = APIRouter(tags=["inventory"])


async def _load_po_out(session: AsyncSession, po: PurchaseOrder) -> PurchaseOrder:
    lines = (
        await session.scalars(
            select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)
        )
    ).all()
    po.lines = list(lines)
    return po


@router.post("/api/v1/vendors", response_model=VendorOut, status_code=status.HTTP_201_CREATED)
async def create_vendor_endpoint(
    body: VendorIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    vendor = await create_vendor(
        session,
        restaurant_id=restaurant.id,
        name=body.name,
        phone=body.phone,
        email=body.email,
        notes=body.notes,
    )
    await session.commit()
    await session.refresh(vendor)
    return vendor


@router.get("/api/v1/vendors", response_model=list[VendorOut])
async def list_vendors_endpoint(
    active_only: bool = Query(default=True),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_vendors(
        session, restaurant_id=restaurant.id, active_only=active_only
    )


@router.patch("/api/v1/vendors/{vendor_id}", response_model=VendorOut)
async def update_vendor_endpoint(
    vendor_id: int,
    body: VendorPatch,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        vendor = await update_vendor(
            session,
            restaurant_id=restaurant.id,
            vendor_id=vendor_id,
            **body.model_dump(exclude_unset=True),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(vendor)
    return vendor


@router.post(
    "/api/v1/purchase-orders",
    response_model=PurchaseOrderOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_purchase_order_endpoint(
    body: PurchaseOrderIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        po = await create_purchase_order(
            session,
            restaurant_id=restaurant.id,
            vendor_id=body.vendor_id,
            lines=[line.model_dump() for line in body.lines],
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(po)
    return await _load_po_out(session, po)


@router.get("/api/v1/purchase-orders", response_model=list[PurchaseOrderOut])
async def list_purchase_orders_endpoint(
    status_filter: str | None = Query(default=None, alias="status"),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    pos = await list_purchase_orders(
        session, restaurant_id=restaurant.id, status=status_filter
    )
    return [await _load_po_out(session, po) for po in pos]


@router.post("/api/v1/purchase-orders/{po_id}/receive", response_model=PurchaseOrderOut)
async def receive_purchase_order_endpoint(
    po_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        po = await receive_purchase_order(session, restaurant_id=restaurant.id, po_id=po_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(po)
    return await _load_po_out(session, po)


@router.post("/api/v1/grn", response_model=GrnOut, status_code=status.HTTP_201_CREATED)
async def create_grn_endpoint(
    body: GrnIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Goods received note — supports partial PO receiving."""
    try:
        grn = await create_grn(
            session,
            restaurant_id=restaurant.id,
            po_id=body.po_id,
            lines=[line.model_dump() for line in body.lines],
            received_by="manager",
            notes=body.notes,
        )
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg else 422
        raise HTTPException(status_code=code, detail=msg) from exc
    await session.commit()
    await session.refresh(grn)
    return grn


@router.get("/api/v1/grn", response_model=list[GrnOut])
async def list_grn_endpoint(
    po_id: int | None = Query(default=None),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_grns(session, restaurant_id=restaurant.id, po_id=po_id)
