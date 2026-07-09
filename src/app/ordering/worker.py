"""Celery tasks for ordering (scheduled/pre-order release)."""

from __future__ import annotations

import asyncio
import logging

from apps.workers.celery_app import celery_app

_logger = logging.getLogger(__name__)


@celery_app.task(name="ordering.release_due_scheduled")
def release_due_scheduled() -> dict:
    """Beat task: release all due scheduled/pre-orders across tenants."""
    from app.db import async_session_factory
    from app.ordering.scheduled import release_due_scheduled_orders

    async def _run() -> dict:
        async with async_session_factory() as session:
            released = await release_due_scheduled_orders(session)
            await session.commit()
            return {
                "released_count": len(released),
                "order_ids": [o.id for o in released],
            }

    try:
        return asyncio.run(_run())
    except Exception:  # noqa: BLE001
        _logger.exception("ordering.release_due_scheduled failed")
        raise
