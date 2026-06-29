"""Celery beat: nightly loyalty tier recompute across all tenants.

Per restaurant (loyalty enabled), recompute every customer's tier from the
restaurant's own settings — picks up threshold edits, demotes lapsed customers
(after grace), and issues welcome rewards on upgrades. On-delivery recompute
handles the live path; this is the catch-all for customers who simply went quiet.
"""
from __future__ import annotations

import asyncio
import logging

from celery import shared_task
from sqlalchemy import select

from app.db import async_session_factory
from app.identity.models import Restaurant
from app.loyalty import service as loyalty
from app.ordering.models import Customer

logger = logging.getLogger(__name__)


@shared_task(name="loyalty.recompute_all_tenants", bind=True, max_retries=0)
def recompute_all_tenants(self) -> int:  # type: ignore[override]
    return asyncio.run(_run())


async def _run() -> int:
    changed = 0
    async with async_session_factory() as session:
        restaurants = (await session.scalars(select(Restaurant))).all()
        for r in restaurants:
            settings = r.settings or {}
            if not (settings.get("loyalty", {}) or {}).get("enabled"):
                continue
            customers = (
                await session.scalars(
                    select(Customer).where(Customer.restaurant_id == r.id)
                )
            ).all()
            for c in customers:
                did, _, _ = await loyalty.recompute_tier(
                    session, customer=c, settings=settings
                )
                if did:
                    changed += 1
            await session.commit()
    if changed:
        logger.info("loyalty nightly recompute: %d tier change(s)", changed)
    return changed
