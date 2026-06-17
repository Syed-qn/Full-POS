from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.models import CodCollection
from app.db import get_session
from app.identity.deps import current_restaurant

router = APIRouter(prefix="/api/v1/cod", tags=["cod"])


@router.get("/shift/{rider_id}")
async def get_shift_collections(
    rider_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """List a rider's COD collections for the current tenant."""
    rows = (
        await session.scalars(
            select(CodCollection).where(
                CodCollection.restaurant_id == restaurant.id,
                CodCollection.rider_id == rider_id,
            )
        )
    ).all()
    return {
        "rider_id": rider_id,
        "collections": [
            {
                "order_id": r.order_id,
                "amount_aed": str(r.amount_aed),
                "collected_at": r.collected_at.isoformat(),
            }
            for r in rows
        ],
    }
