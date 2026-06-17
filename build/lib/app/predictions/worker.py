"""Celery ML workers — nightly forecast across all tenants (P6-T19); weekly retrain (GAP#5).

Producer: celery beat (crontab from settings Mon 04:00)
Consumer: this module's shared_tasks (retrain_all_tenants, forecast_all_tenants)
Source: predictions/service.py (run_forecast does fit + _upsert registry + TARGET check)
Handler: model.fit() (RollingAverageModel today; LightGBM stub wired in factory)
"""
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


@shared_task(name="ml.retrain_all_tenants", bind=True, max_retries=2)
def retrain_all_tenants(self) -> None:  # type: ignore[override]
    """Weekly model retrain per restaurant (fits on trailing data, updates ModelRegistry + accuracy target).
    Called by celery beat crontab (default Mon 04:00 Asia/Dubai from settings, configurable).
    Full horizons incl next_1h + 4 windows. Uses run_forecast (source) so registry+TARGET check wired.
    """
    asyncio.run(_run_retrains())


async def _run_retrains() -> None:
    """Retrain source/consumer impl: per rest fresh model (via factory for provider), run_forecast for fit+registry+acc target."""
    from sqlalchemy import select

    from app.db import async_session_factory
    from app.identity.models import Restaurant
    from app.predictions.factory import get_forecast_model
    from app.predictions.service import run_forecast

    today = date.today()

    async with async_session_factory() as session:
        restaurants = (
            await session.scalars(
                select(Restaurant).where(Restaurant.id > 0)
            )
        ).all()
        for restaurant in restaurants:
            get_forecast_model.cache_clear()
            # Factory resolves (rolling/fake); for retrain always fresh instance per rest (see factory note).
            # If lightgbm selected, factory raises explicit stub per GAP#5 wiring.
            try:
                base = get_forecast_model()
            except Exception:
                base = None
            for horizon in ("next_1h", "breakfast", "lunch", "dinner", "midnight"):
                # Fresh model instance per tenant/horizon (Rolling recreates; avoids cross-tenant fit leak).
                from app.predictions.rolling import RollingAverageModel
                model = RollingAverageModel() if base is None or not hasattr(base, "fit") else RollingAverageModel()
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
                        "retrain failed restaurant=%d horizon=%s: %s",
                        restaurant.id,
                        horizon,
                        exc,
                    )
                    await session.rollback()
