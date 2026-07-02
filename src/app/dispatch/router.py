"""Dispatch endpoints — trigger + assignment explainability (spec §4.3, §5.6)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.dispatch.models import Assignment
from app.dispatch.kpis import compute_dispatch_kpis
from app.dispatch.live_map import build_live_ops_map
from app.dispatch.schemas import (
    AssignmentExplainOut,
    DispatchKpisOut,
    LiveOpsMapOut,
)
from app.dispatch.service import run_dispatch
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.ordering.models import Order

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
    from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

    await flush_pending_partner_webhooks(session, restaurant_id=restaurant.id)
    return {
        "assigned": result.assigned_count,
        "unassigned": result.unassigned_count,
        "needs_retry": result.needs_retry,
    }


@router.get("/kpis", response_model=DispatchKpisOut)
async def get_dispatch_kpis(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> DispatchKpisOut:
    """Batch rate, avg stops, and engine fallback % for the manager dashboard."""
    data = await compute_dispatch_kpis(session, restaurant_id=restaurant.id)
    return DispatchKpisOut(**data)


@router.get("/live-map", response_model=LiveOpsMapOut)
async def get_live_ops_map(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> LiveOpsMapOut:
    """Active batch polylines and SLA pressure rings for the live ops map."""
    data = await build_live_ops_map(session, restaurant=restaurant)
    return LiveOpsMapOut(**data)


@router.get("/assignments", response_model=list[AssignmentExplainOut])
async def list_assignments(
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[Assignment]:
    """List dispatch assignments with explainability payloads for this restaurant."""
    return list(
        (
            await session.scalars(
                select(Assignment)
                .join(Order, Assignment.order_id == Order.id)
                .where(Order.restaurant_id == restaurant.id)
                .order_by(Assignment.assigned_at.desc())
            )
        ).all()
    )
