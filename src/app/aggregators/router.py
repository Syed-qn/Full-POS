from datetime import date

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.aggregators.factory import get_aggregator_port
from app.aggregators.service import ingest_inbound_order, reconciliation
from app.db import get_session
from app.identity.deps import current_restaurant
from app.partner.deps import partner_authenticated_restaurant

router = APIRouter(prefix="/api/v1/aggregators", tags=["aggregators"])


@router.post("/{provider}/webhook", status_code=status.HTTP_201_CREATED)
async def aggregator_webhook(
    provider: str,
    payload: dict = Body(...),
    # Real aggregators call this endpoint directly — they never hold a manager
    # JWT — so this authenticates the same way any other external partner
    # system does: a restaurant-issued X-API-Key (see app.partner).
    restaurant=Depends(partner_authenticated_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        gateway = get_aggregator_port(provider)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        order = await ingest_inbound_order(
            session, restaurant_id=restaurant.id, provider=provider, payload=payload, gateway=gateway,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"malformed {provider} payload: {exc}") from exc
    await session.commit()
    return {"order_id": order.id, "order_number": order.order_number}


@router.get("/reconciliation")
async def get_reconciliation(
    start_date: date, end_date: date,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    result = await reconciliation(session, restaurant_id=restaurant.id, start_date=start_date, end_date=end_date)
    return {
        provider: {"order_count": v["order_count"], "revenue_aed": str(v["revenue_aed"])}
        for provider, v in result.items()
    }
