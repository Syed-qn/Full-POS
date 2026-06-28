"""Celery beat tasks for wallet maintenance: credit expiry + reconciliation.

Both iterate tenants. Expiry posts lapsed-credit debits; reconcile re-sums each
tenant's ledger and logs drift (a nonzero drift is a data-integrity alarm).
"""
from __future__ import annotations

import asyncio
import logging

from celery import shared_task
from sqlalchemy import select

from app.config import get_settings
from app.db import async_session_factory
from app.identity.models import Restaurant
from app.wallet.reconcile import expire_credits, reconcile_tenant

logger = logging.getLogger(__name__)


@shared_task(name="wallet.expire_credits_all_tenants", bind=True, max_retries=0)
def expire_credits_all_tenants(self) -> int:  # type: ignore[override]
    return asyncio.run(_run_expiry())


async def _run_expiry() -> int:
    ttl = get_settings().wallet_credit_ttl_days
    if ttl <= 0:
        return 0
    total = 0
    async with async_session_factory() as session:
        rids = (await session.scalars(select(Restaurant.id))).all()
        for rid in rids:
            n = await expire_credits(session, restaurant_id=rid, ttl_days=ttl)
            total += n
        await session.commit()
    if total:
        logger.info("wallet expiry: expired credit on %d account(s)", total)
    return total


@shared_task(name="wallet.reconcile_all_tenants", bind=True, max_retries=0)
def reconcile_all_tenants(self) -> int:  # type: ignore[override]
    return asyncio.run(_run_reconcile())


async def _run_reconcile() -> int:
    drift_count = 0
    async with async_session_factory() as session:
        rids = (await session.scalars(select(Restaurant.id))).all()
        for rid in rids:
            result = await reconcile_tenant(session, restaurant_id=rid)
            if result["drift_aed"] != 0:
                drift_count += 1
                logger.error(
                    "WALLET DRIFT tenant=%s liability=%s control=%s drift=%s",
                    rid, result["liability_aed"], result["control_aed"], result["drift_aed"],
                )
    return drift_count
