"""Catalog flow HTTP surface (manager-authed).

A small endpoint to push the WhatsApp catalog (multi-product message) to a phone,
so a manager can test the catalog ordering experience on demand. The customer-facing
trigger lives in the webhook (keyword), this is for manual sends / testing.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.service import send_catalog
from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.outbox.service import deliver_pending

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


class SendCatalogIn(BaseModel):
    phone: str


@router.post("/send")
async def send_catalog_to_phone(
    body: SendCatalogIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Send the catalog (tappable product cards) to a phone. For testing the flow."""
    phone = body.phone.strip()
    if not phone:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "phone required")
    sent = await send_catalog(session, restaurant_id=restaurant.id, to_phone=phone)
    if not sent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "no catalog_id configured or no linked, available products for this restaurant",
        )
    await session.commit()
    await deliver_pending(session, restaurant.id)
    return {"status": "sent", "phone": phone}
