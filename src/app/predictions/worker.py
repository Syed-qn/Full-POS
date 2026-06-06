"""Celery ML workers — nightly forecast across all tenants (P6-T19)."""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="ml.forecast_all_tenants", bind=True, max_retries=2)
def forecast_all_tenants(self) -> None:  # type: ignore[override]
    """Run nightly demand forecast for every active restaurant."""
    asyncio.run(_run_forecasts())


async def _run_forecasts() -> None:
    from sqlalchemy import select

    from app.db import async_session_factory
    from app.identity.models import Restaurant
    from app.llm.fake import FakeForecastAdjuster  # noqa: F401 (kept for future adjuster use)
    from app.predictions.rolling import RollingAverageModel
    from app.predictions.service import run_forecast

    today = date.today()

    async with async_session_factory() as session:
        restaurants = (
            await session.scalars(
                select(Restaurant).where(Restaurant.id > 0)
            )
        ).all()
        for restaurant in restaurants:
            for horizon in ("breakfast", "lunch", "dinner", "midnight"):
                # Fresh model per restaurant so fit() state doesn't leak across tenants.
                model = RollingAverageModel()
                try:
                    await run_forecast(
                        session,
                        restaurant_id=restaurant.id,
                        target_date=today,
                        horizon=horizon,
                        model=model,
                    )
                    await session.commit()
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "forecast failed restaurant=%d horizon=%s: %s",
                        restaurant.id,
                        horizon,
                        exc,
                    )
                    await session.rollback()
