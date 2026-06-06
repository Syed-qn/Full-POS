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
                await run_campaign_send(
                    session,
                    campaign=campaign,
                    provider=provider,
                    now_utc=now_utc,
                )
                await session.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("campaign send failed id=%d: %s", campaign.id, exc)
                await session.rollback()
