"""Periodic dispatch sweep (Celery beat).

Runs the dispatch engine for every restaurant that currently has ready, unassigned
orders. Two reasons this must be periodic rather than purely event-driven (the
``_auto_dispatch_on_ready`` hook that fires when a kitchen marks an order ready):

  1. Batch hold window — a freshly-ready lone order is intentionally HELD for up to
     ``batch_hold_seconds`` so a neighbour can join its batch. The sweep is what
     re-evaluates and releases it once the window matures (or a mate appears).
  2. No-rider retry — an order left ready because no rider was free would otherwise
     sit forever until some *other* order happened to become ready. The sweep retries
     it every tick (the no-rider manager alert is idempotency-bucketed to avoid spam).

Idempotent and best-effort: a failure for one restaurant never blocks the others.
"""
from __future__ import annotations

import asyncio
import logging

from celery import shared_task
from sqlalchemy import select

from app.db import async_session_factory
from app.dispatch.service import run_dispatch_engine
from app.ordering.models import Order

logger = logging.getLogger(__name__)


@shared_task(name="dispatch.sweep_ready", bind=True, max_retries=3, default_retry_delay=10)
def dispatch_sweep_ready(self) -> None:  # type: ignore[override]
    asyncio.run(_run_sweep())


async def _run_sweep() -> None:
    async with async_session_factory() as session:
        restaurant_ids = (
            await session.scalars(
                select(Order.restaurant_id)
                .where(Order.status == "ready", Order.rider_id.is_(None))
                .distinct()
            )
        ).all()
    for restaurant_id in restaurant_ids:
        # Fresh session per restaurant so one tenant's failure can't poison another's.
        async with async_session_factory() as session:
            try:
                await run_dispatch_engine(session, restaurant_id=restaurant_id)
                await session.commit()
            except Exception:  # noqa: BLE001 — best-effort; keep sweeping other tenants
                logger.exception(
                    "dispatch sweep failed for restaurant_id=%s", restaurant_id
                )
                await session.rollback()
