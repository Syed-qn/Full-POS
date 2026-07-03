"""Celery marketing workers — scheduled campaign dispatch (P6-T19)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="marketing.send_scheduled_campaigns", bind=True, max_retries=2)
def send_scheduled_campaigns(self) -> None:  # type: ignore[override]
    asyncio.run(_dispatch_scheduled())


async def _dispatch_scheduled() -> None:
    from sqlalchemy import select

    from app.db import async_session_factory
    from app.marketing.models import Campaign
    from app.marketing.service import run_campaign_send
    from app.marketing.template_factory import get_template_provider

    provider = get_template_provider()
    now_utc = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        due_campaigns = (
            await session.scalars(
                select(Campaign).where(
                    Campaign.status == "scheduled",
                    Campaign.scheduled_at <= now_utc,
                )
            )
        ).all()
        for campaign in due_campaigns:
            try:
                stats_ids = (campaign.stats or {}).get("audience_ids")
                audience_ids = (
                    [int(x) for x in stats_ids]
                    if isinstance(stats_ids, list) and stats_ids
                    else None
                )
                await run_campaign_send(
                    session,
                    campaign=campaign,
                    provider=provider,
                    now_utc=now_utc,
                    audience_ids=audience_ids,
                )
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("campaign send failed id=%d: %s", campaign.id, exc)
                await session.rollback()


# ---------------------------------------------------------------------------
# GAP#3: Meta poll (every 2min) + EOD ephemeral auto-delete (23:30 Dubai)
# Per phase-6 plan + GAP_LIST: poll pending_meta -> update via provider;
# cleanup ephemeral created-today -> provider.delete + set deleted_at (for
# 30d blackout). Producer=beat in celery_app, source=service, consumer/handler=these.
# Use same async session pattern + get_template_provider.
# ---------------------------------------------------------------------------

@shared_task(name="marketing.poll_template_statuses", bind=True, max_retries=2)
def poll_template_statuses(self) -> None:  # type: ignore[override]
    asyncio.run(_poll_template_statuses())


async def _poll_template_statuses() -> None:
    from app.db import async_session_factory
    from app.marketing.service import poll_template_statuses as svc_poll
    from app.marketing.template_factory import get_template_provider

    provider = get_template_provider()
    async with async_session_factory() as session:
        try:
            n = await svc_poll(session, provider=provider)
            await session.commit()
            if n:
                logger.info("poll_template_statuses updated %d", n)
            return n
        except Exception as exc:  # noqa: BLE001
            logger.warning("poll_template_statuses failed: %s", exc)
            await session.rollback()
            return 0


@shared_task(name="marketing.cleanup_ephemeral_templates", bind=True, max_retries=1)
def cleanup_ephemeral_templates(self) -> None:  # type: ignore[override]
    asyncio.run(_cleanup_ephemeral_templates())


async def _cleanup_ephemeral_templates(now: datetime | None = None) -> None:
    from app.db import async_session_factory
    from app.marketing.service import cleanup_ephemeral_templates as svc_cleanup
    from app.marketing.template_factory import get_template_provider

    provider = get_template_provider()
    now = now or datetime.now(timezone.utc)
    async with async_session_factory() as session:
        try:
            n = await svc_cleanup(session, provider=provider, now=now)
            await session.commit()
            if n:
                logger.info("cleanup_ephemeral_templates deleted %d", n)
            return n
        except Exception as exc:  # noqa: BLE001
            logger.warning("cleanup_ephemeral_templates failed: %s", exc)
            await session.rollback()
            return 0


@shared_task(name="marketing.automation_tick", bind=True, max_retries=2)
def automation_tick(self) -> None:  # type: ignore[override]
    asyncio.run(_automation_tick())


async def _automation_tick() -> None:
    from app.db import async_session_factory
    from app.marketing.service import run_automation_tick
    from app.marketing.template_factory import get_template_provider

    provider = get_template_provider()
    now_utc = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        try:
            totals = await run_automation_tick(
                session, now_utc=now_utc, provider=provider
            )
            await session.commit()
            if totals.get("queued"):
                logger.info("automation_tick queued=%d", totals["queued"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("automation_tick failed: %s", exc)
            await session.rollback()


@shared_task(name="marketing.recurring_promo_tick", bind=True, max_retries=2)
def recurring_promo_tick(self) -> None:  # type: ignore[override]
    asyncio.run(_recurring_promo_tick())


async def _recurring_promo_tick() -> None:
    from app.db import async_session_factory
    from app.marketing.service import run_recurring_promo_tick
    from app.marketing.template_factory import get_template_provider

    provider = get_template_provider()
    now_utc = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        try:
            totals = await run_recurring_promo_tick(
                session, now_utc=now_utc, provider=provider
            )
            await session.commit()
            if totals.get("queued"):
                logger.info("recurring_promo_tick queued=%d", totals["queued"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("recurring_promo_tick failed: %s", exc)
            await session.rollback()
