"""Unauthenticated public endpoints for QR table ordering."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.ordering.schemas import QrOrderIn

router = APIRouter(prefix="/api/v1/public/qr", tags=["public-qr"])


@router.post("/{qr_token}/orders")
async def public_qr_order(
    qr_token: str,
    body: QrOrderIn,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Place a QR-table order without manager auth (token is the capability)."""
    from app.ordering.qr_orders import create_qr_order

    try:
        order = await create_qr_order(
            session,
            qr_token=qr_token,
            customer_phone=body.customer_phone,
            customer_name=body.customer_name,
            items=[i.model_dump() for i in body.items],
        )
        order.source_channel = "qr"
    except ValueError as exc:
        msg = str(exc)
        code = 404 if "invalid QR" in msg.lower() else 422
        raise HTTPException(status_code=code, detail=msg) from exc
    await session.commit()
    return {
        "id": order.id,
        "order_number": order.order_number,
        "status": order.status,
        "order_type": order.order_type,
        "source_channel": order.source_channel,
        "table_id": order.table_id,
        "total_aed": str(order.total),
    }
