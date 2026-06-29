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
from app.ratelimit.deps import rate_limit_webhook
from app.webhook.models import WebhookEvent
from app.webhook.normalizer import parse_cloud_payload
from app.whatsapp.port import MessageType

# Importing the configured Celery app sets it as the default, binding @shared_task
# tasks (e.g. deliver_outbox_message) to the redis broker instead of the amqp default.
import apps.workers.celery_app  # noqa: E402,F401

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])

# Customer text that should surface the WhatsApp catalog (when the restaurant has
# catalog ordering enabled). Kept here (webhook layer) so the conversation engine
# is never touched.
_CATALOG_KEYWORDS = {"menu", "catalog", "catalogue", "order", "items", "list"}


def _wants_catalog(inbound, restaurant) -> bool:
    if inbound.type != MessageType.TEXT:
        return False
    settings = getattr(restaurant, "settings", None) or {}
    if not settings.get("catalog_ordering_enabled"):
        return False
    text = (inbound.payload or {}).get("text", "")
    return text.strip().lower() in _CATALOG_KEYWORDS


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
    _rl: None = Depends(rate_limit_webhook),
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
                processed_at=datetime.now(timezone.utc),
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
            # WhatsApp catalog carts go to the SEPARATE catalog flow, never the
            # conversation engine. Everything else (text, voice, buttons, location)
            # is handled by the engine exactly as before.
            if inbound.type == MessageType.ORDER:
                from app.catalog.service import handle_catalog_order

                await handle_catalog_order(session, inbound, restaurant_id=restaurant.id)
            elif _wants_catalog(inbound, restaurant):
                # Customer asked for the catalog/menu and this restaurant has catalog
                # ordering on → send tappable product cards instead of the text bot.
                from app.catalog.service import send_catalog

                await send_catalog(
                    session,
                    restaurant_id=restaurant.id,
                    to_phone=inbound.from_phone,
                    idempotency_key=f"catalog-kw-{inbound.wa_message_id}",
                )
            else:
                await handle_inbound(session, inbound, restaurant_id=restaurant.id)

            # Atomically claim the restaurant's pending outbox rows
            # (pending -> dispatching) BEFORE committing so concurrent webhooks
            # racing the same rows can't double-dispatch. Only the winning
            # transaction gets the ids back; losers claim nothing. We flush ALL
            # of the restaurant's pending rows (not just replies to this sender)
            # because a single inbound can fan out to several recipients — e.g. a
            # rider's "Orders Picked" tap sends the rider their next stop AND the
            # customer an "on the way" update; a per-sender claim would strand the
            # other recipient's message as pending forever (no beat sweeper here).
            claimed_ids = await claim_pending_outbox_ids(
                session,
                restaurant_id=restaurant.id,
            )
            await session.commit()

            if settings.outbox_sync_delivery:
                # No worker: deliver each reply in-request on this same connection
                # (mirrors the simulator's synchronous path). Bind a sessionmaker to
                # this session's connection so _deliver_one reuses it.
                from sqlalchemy.ext.asyncio import async_sessionmaker

                from app.outbox.worker import _deliver_one
                from app.whatsapp.factory import get_whatsapp_provider

                provider = get_whatsapp_provider()
                sync_factory = async_sessionmaker(
                    bind=session.bind,
                    expire_on_commit=False,
                    join_transaction_mode="create_savepoint",
                )
                for outbox_id in claimed_ids:
                    await _deliver_one(outbox_id, provider=provider, session_factory=sync_factory)
            else:
                for outbox_id in claimed_ids:
                    deliver_outbox_message.apply_async(args=[outbox_id], queue="outbox")

        except IntegrityError:
            await session.rollback()
            logger.warning(
                "integrity error processing event %s — idempotency collision",
                inbound.wa_message_id,
            )
        except Exception:
            # SAFETY NET: any unexpected error while processing one message must not
            # silently 500 the whole webhook batch (which strands every other message
            # and triggers WhatsApp retry storms). Roll back this message, log loudly
            # with a traceback so the drop is never silent, and carry on with the rest.
            await session.rollback()
            logger.error(
                "unexpected error processing event %s for restaurant phone %s — "
                "message dropped, continuing batch",
                inbound.wa_message_id, inbound.restaurant_phone, exc_info=True,
            )
            # Respond like a human instead of going silent — the customer gets a brief
            # apology, never a raw error and never the wrong menu. Best-effort on a
            # FRESH session (the request one is rolled back); never let this raise.
            try:
                await _send_error_apology(
                    restaurant_phone=inbound.restaurant_phone,
                    to_phone=inbound.from_phone,
                    wa_message_id=inbound.wa_message_id,
                )
            except Exception:
                logger.error("failed to send error apology for %s",
                             inbound.wa_message_id, exc_info=True)

    return {"status": "ok"}


async def _send_error_apology(*, restaurant_phone: str, to_phone: str, wa_message_id: str) -> None:
    """Send a one-line human apology after an unexpected processing error, on a fresh
    session so it is independent of the rolled-back request transaction. Idempotent per
    inbound message id, so WhatsApp retries can't spam the customer."""
    from app.db import async_session_factory
    from app.outbox.service import deliver_outbox_now, enqueue_message
    from app.whatsapp.port import OutboundMessageType

    async with async_session_factory() as s:
        rest = await s.scalar(select(Restaurant).where(Restaurant.phone == restaurant_phone))
        if rest is None:
            return
        row = await enqueue_message(
            s,
            restaurant_id=rest.id,
            to_phone=to_phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "Sorry, something went wrong on our end 🙏 Please send that "
                             "again in a moment and we'll take care of it."},
            idempotency_key=f"err-apology-{wa_message_id}",
        )
        await s.flush()
        await s.commit()
        await deliver_outbox_now(s, [row.id])
