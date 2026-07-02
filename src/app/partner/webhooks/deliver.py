"""HTTP delivery of one partner webhook row."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.identity.models import Restaurant
from app.partner.integration import partner_settings
from app.partner.webhooks.models import PartnerWebhookDelivery
from app.partner.webhooks.signing import sign_body

logger = logging.getLogger(__name__)

_TERMINAL = ("sent", "dead")
_MAX_ATTEMPTS = 5


def _is_permanent_failure(status_code: int) -> bool:
    return 400 <= status_code < 500 and status_code != 429


async def deliver_partner_webhook_one(
    delivery_id: int,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    client: httpx.AsyncClient | None = None,
) -> None:
    """POST one queued webhook to the partner URL. Updates row status in DB."""
    async with session_factory() as session:
        row = await session.get(PartnerWebhookDelivery, delivery_id)
        if row is None or row.status in _TERMINAL:
            return

        restaurant = await session.get(Restaurant, row.restaurant_id)
        secret = ""
        if restaurant is not None:
            secret = partner_settings(restaurant)["partner_webhook_secret"]

        body_bytes = json.dumps(row.payload, separators=(",", ":"), sort_keys=True).encode(
            "utf-8"
        )
        headers = {
            "Content-Type": "application/json",
            "X-Partner-Event": row.event_type,
            "X-Partner-Idempotency-Key": row.idempotency_key,
        }
        if secret:
            headers["X-Partner-Signature"] = sign_body(secret, body_bytes)

        owns_client = client is None
        http = client or httpx.AsyncClient(timeout=10.0)
        try:
            resp = await http.post(row.target_url, content=body_bytes, headers=headers)
            row.attempts += 1
            if 200 <= resp.status_code < 300:
                row.status = "sent"
                row.delivered_at = datetime.now(timezone.utc)
                row.last_error = None
            elif _is_permanent_failure(resp.status_code):
                row.status = "dead"
                row.last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
            elif row.attempts >= _MAX_ATTEMPTS:
                row.status = "dead"
                row.last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
            else:
                row.status = "failed"
                row.last_error = f"HTTP {resp.status_code}: {resp.text[:500]}"
        except Exception as exc:  # noqa: BLE001
            row.attempts += 1
            row.last_error = str(exc)[:500]
            logger.warning("partner webhook delivery failed id=%s: %s", delivery_id, exc)
            if row.attempts >= _MAX_ATTEMPTS:
                row.status = "dead"
            else:
                row.status = "failed"
        finally:
            if owns_client:
                await http.aclose()
        await session.commit()