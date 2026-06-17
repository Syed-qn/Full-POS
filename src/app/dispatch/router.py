"""Dispatch trigger endpoint — POST /api/v1/dispatch/trigger (spec §4.3)."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.dispatch.service import run_dispatch
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant

router = APIRouter(prefix="/api/v1/dispatch", tags=["dispatch"])


@router.post("/trigger")
async def trigger_dispatch(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> dict:
    """Manually trigger the dispatch engine for this restaurant."""
    result = await run_dispatch(session, restaurant_id=restaurant.id)
    await session.commit()
    # Deliver the rider/manager notifications the engine enqueued — the manual
    # trigger has no delivery step of its own (unlike event-driven auto-dispatch).
    from app.outbox.service import deliver_pending

    await deliver_pending(session, restaurant.id)
    return {
        "assigned": result.assigned_count,
        "unassigned": result.unassigned_count,
        "needs_retry": result.needs_retry,
    }
