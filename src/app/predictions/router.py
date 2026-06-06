"""Predictions REST API — forecast runs, prep-ahead suggestions, manager overrides."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.llm.factory import get_forecast_adjuster
from app.predictions.schemas import OverrideRequest, OverrideResponse
from app.predictions.service import (
    create_override,
    latest_run,
    list_runs,
    prep_ahead_suggestions,
)

router = APIRouter(prefix="/api/v1/predictions", tags=["predictions"])


@router.get("/latest")
async def get_latest_forecast(
    horizon: str,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> dict[str, Any]:
    run = await latest_run(session, restaurant_id=restaurant.id, horizon=horizon)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "no forecast for this horizon")
    return {
        "run_id": run.id,
        "horizon": run.horizon,
        "target_date": str(run.target_date),
        "predictions": run.predicted,
        "adjusted": run.adjusted,
    }


@router.get("/runs")
async def list_forecast_runs(
    limit: int = 20,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[dict[str, Any]]:
    runs = await list_runs(session, restaurant_id=restaurant.id, limit=limit)
    return [
        {
            "run_id": r.id,
            "horizon": r.horizon,
            "target_date": str(r.target_date),
        }
        for r in runs
    ]


@router.get("/prep-ahead")
async def get_prep_ahead(
    horizon: str,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> list[dict[str, Any]]:
    """Return prep-ahead suggestions derived from the most recent run for the
    given horizon.  Returns an empty list when no forecast run exists yet."""
    run = await latest_run(session, restaurant_id=restaurant.id, horizon=horizon)
    if run is None:
        return []
    return await prep_ahead_suggestions(
        session,
        restaurant_id=restaurant.id,
        run=run,
    )


@router.post("/overrides", status_code=201)
async def create_forecast_override(
    body: OverrideRequest,
    session: AsyncSession = Depends(get_session),
    restaurant: Restaurant = Depends(current_restaurant),
) -> OverrideResponse:
    adjuster = get_forecast_adjuster()
    now = datetime.now(tz=UTC)
    active_from = now
    active_to = now + timedelta(days=7)
    override = await create_override(
        session,
        restaurant_id=restaurant.id,
        text=body.raw_text,
        adjuster=adjuster,
        active_from=active_from,
        active_to=active_to,
    )
    await session.commit()
    return OverrideResponse(
        id=override.id,
        text=override.text,
        parsed_effect=override.parsed_effect,
    )
