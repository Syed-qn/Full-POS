import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.conversation.engine import handle_inbound
from app.db import get_session
from app.identity.models import Restaurant
from app.outbox.worker import claim_pending_outbox_ids, deliver_outbox_message
from app.webhook.models import WebhookEvent
from app.webhook.normalizer import parse_cloud_payload

# Importing the configured Celery app sets it as the default, binding @shared_task
# tasks (e.g. deliver_outbox_message) to the redis broker instead of the amqp default.
import apps.workers.celery_app  # noqa: E402,F401

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])


@router.get("/webhooks/whatsapp")
async def verify_webhook(request: Request) -> Response:
    """Meta webhook verification handshake."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    settings = get_settings()
    if mode == "subscribe" and token == settings.wa_verify_token:
        return Response(content=challenge, media_type="text/plain")
    raise HTTPException(status.HTTP_403_FORBIDDEN, "invalid verify token")


@router.post("/webhooks/whatsapp")
async def receive_webhook(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Receive inbound WhatsApp events from Meta (or simulator)."""
    body_bytes = await request.body()
    payload = await request.json()
    settings = get_settings()

    # Signature verification — enforced in cloud mode only (mock has no app secret)
    if settings.whatsapp_provider == "cloud":
        from app.whatsapp.cloud_provider import verify_signature

        sig_header = request.headers.get("X-Hub-Signature-256", "")
        try:
            verify_signature(
                body_bytes, sig_header, settings.wa_app_secret.get_secret_value()
            )
        except ValueError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))

    inbound_messages = parse_cloud_payload(payload)

    for inbound in inbound_messages:
        # Idempotency check
        existing = await session.scalar(
            select(WebhookEvent).where(
                WebhookEvent.provider_event_id == inbound.wa_message_id
            )
        )
        if existing is not None:
            logger.info("duplicate webhook event %s — skipping", inbound.wa_message_id)
            continue

        session.add(
            WebhookEvent(
                provider_event_id=inbound.wa_message_id,
                payload=payload,
                processed_at=datetime.now(timezone.utc).isoformat(),
            )
        )

        restaurant = await session.scalar(
            select(Restaurant).where(Restaurant.phone == inbound.restaurant_phone)
        )
        if restaurant is None:
            logger.warning(
                "webhook for unknown restaurant phone %s — skipping",
                inbound.restaurant_phone,
            )
            continue

        try:
            await handle_inbound(session, inbound, restaurant_id=restaurant.id)

            # Atomically claim this conversation's pending outbox rows
            # (pending -> dispatching) BEFORE committing so concurrent webhooks
            # racing the same rows can't double-dispatch to the customer. Only
            # the winning transaction gets the ids back; losers claim nothing.
            claimed_ids = await claim_pending_outbox_ids(
                session,
                to_phone=inbound.from_phone,
                restaurant_id=restaurant.id,
            )
            await session.commit()

            for outbox_id in claimed_ids:
                deliver_outbox_message.apply_async(args=[outbox_id], queue="outbox")

        except IntegrityError:
            await session.rollback()
            logger.warning(
                "integrity error processing event %s — idempotency collision",
                inbound.wa_message_id,
            )

    return {"status": "ok"}
