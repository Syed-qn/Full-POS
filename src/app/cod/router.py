from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.models import CodCollection, RiderShiftReconciliation
from app.cod.service import reconcile_shift
from app.db import get_session
from app.identity.deps import current_restaurant
from app.staff.deps import require_role

router = APIRouter(prefix="/api/v1/cod", tags=["cod"])


class ReconcileIn(BaseModel):
    shift_date: date | None = None
    declared_collected_aed: Decimal | None = Field(default=None, ge=0)


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


@router.post("/shift/{rider_id}/reconcile")
async def reconcile_rider_shift(
    rider_id: int,
    body: ReconcileIn | None = None,
    restaurant=Depends(require_role("manager")),
    session: AsyncSession = Depends(get_session),
):
    """Reconcile rider COD for a shift date (expected = delivered COD due)."""
    body = body or ReconcileIn()
    shift_date = body.shift_date or date.today()
    try:
        rec = await reconcile_shift(
            session,
            restaurant_id=restaurant.id,
            rider_id=rider_id,
            shift_date=shift_date,
            declared_collected_aed=body.declared_collected_aed,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    return {
        "id": rec.id,
        "rider_id": rec.rider_id,
        "shift_date": rec.shift_date.isoformat(),
        "expected_total_aed": str(rec.expected_total_aed),
        "collected_total_aed": str(rec.collected_total_aed),
        "variance_aed": str(rec.variance_aed),
        "status": rec.status,
    }


@router.get("/reconciliations")
async def list_reconciliations(
    rider_id: int | None = Query(default=None),
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    q = select(RiderShiftReconciliation).where(
        RiderShiftReconciliation.restaurant_id == restaurant.id
    )
    if rider_id is not None:
        q = q.where(RiderShiftReconciliation.rider_id == rider_id)
    rows = list((await session.scalars(q.order_by(RiderShiftReconciliation.id.desc()).limit(50))).all())
    return [
        {
            "id": r.id,
            "rider_id": r.rider_id,
            "shift_date": r.shift_date.isoformat(),
            "expected_total_aed": str(r.expected_total_aed),
            "collected_total_aed": str(r.collected_total_aed),
            "variance_aed": str(r.variance_aed),
            "status": r.status,
        }
        for r in rows
    ]
