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
from app.webhook.normalizer import parse_cloud_payload, slice_message_payload
from app.webhook.routing import resolve_restaurant_for_webhook
from app.whatsapp.port import MessageType

# Importing the configured Celery app sets it as the default, binding @shared_task
# tasks (e.g. deliver_outbox_message) to the redis broker instead of the amqp default.
import apps.workers.celery_app  # noqa: E402,F401

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhook"])

# NOTE: the old _wants_catalog keyword shortcut (route "menu"/"order" texts
# straight to send_catalog, bypassing the engine) was deleted deliberately: it
# ignored manual takeover, recorded neither side of the turn in history, and
# hijacked bare "order"/"list" mid-checkout. The engine's cross-phase
# _is_menu_request → _send_menu_or_catalog path covers every keyword
# (incl. misspellings + the bare intent words) with takeover, recording,
# cooldown and phase-awareness.


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

    _log_webhook_summary(payload)

    # Delivery-status events (value.statuses). Previously dropped entirely — a
    # message Meta accepted but later FAILED to deliver (closed 24h window,
    # blocked recipient) vanished: bot believed it replied, customer saw nothing.
    await _process_status_events(session, payload)

    inbound_messages = parse_cloud_payload(payload)

    for inbound in inbound_messages:
        # Insert-first idempotency: claim the event BEFORE any engine work so a
        # concurrent duplicate webhook never runs handle_inbound twice (the old
        # check-then-insert let the loser do full processing, then roll back).
        if not await _try_claim_webhook_event(
            session,
            provider_event_id=inbound.wa_message_id,
            payload=slice_message_payload(payload, inbound.wa_message_id),
        ):
            logger.info("duplicate webhook event %s — skipping", inbound.wa_message_id)
            continue

        restaurant = await resolve_restaurant_for_webhook(
            session,
            restaurant_phone=inbound.restaurant_phone,
            phone_number_id=inbound.phone_number_id,
        )
        if restaurant is None:
            logger.warning(
                "webhook for unknown restaurant phone=%s phone_number_id=%s — skipping",
                inbound.restaurant_phone,
                inbound.phone_number_id or "(none)",
            )
            continue

        try:
            # WhatsApp catalog carts go to the SEPARATE catalog flow, never the
            # conversation engine. Everything else (text, voice, buttons, location)
            # is handled by the engine exactly as before.
            if inbound.type == MessageType.ORDER:
                from app.catalog.service import handle_catalog_order

                await handle_catalog_order(session, inbound, restaurant_id=restaurant.id)
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
            # Customer turns: deliver only THIS sender's pending rows so a "menu"
            # reply isn't blocked behind hundreds of stale rows for other phones
            # (Render sync-delivery holds the webhook open for every claimed send).
            # Rider turns may fan out to customer + rider in one txn — flush all.
            from app.conversation.engine import _resolve_counterpart
            from app.identity.phones import normalize_phone

            _counterpart, _ = await _resolve_counterpart(
                session, restaurant.id, inbound.from_phone
            )
            if _counterpart == "rider":
                claimed_ids = await claim_pending_outbox_ids(
                    session, restaurant_id=restaurant.id
                )
            else:
                claimed_ids = await claim_pending_outbox_ids(
                    session,
                    restaurant_id=restaurant.id,
                    to_phone=normalize_phone(inbound.from_phone),
                )
            await session.commit()

            # Post-commit delivery is best-effort only. The customer's turn (order
            # placed, reply enqueued) is already durable — a Celery broker blip or a
            # partner-webhook schedule failure must never send the generic "something
            # went wrong" apology on top of a successful confirmation (prod: Order
            # #R1-0140 got confirm + apology when apply_async raised here).
            await _schedule_post_commit_delivery(
                session,
                restaurant_id=restaurant.id,
                claimed_ids=claimed_ids,
                outbox_sync_delivery=settings.outbox_sync_delivery,
            )

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


def _log_webhook_summary(payload: dict) -> None:
    """Log every Meta POST so prod Render logs show which WABA/phone fired."""
    parts: list[str] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            meta = value.get("metadata", {})
            pid = meta.get("phone_number_id") or "?"
            disp = meta.get("display_phone_number") or "?"
            msgs = value.get("messages") or []
            stats = value.get("statuses") or []
            if msgs:
                for msg in msgs:
                    text = (msg.get("text") or {}).get("body") or msg.get("type") or "?"
                    parts.append(
                        f"pid={pid} display={disp} IN from={msg.get('from')} "
                        f"type={msg.get('type')} text={text!r}"
                    )
            if stats:
                for st in stats:
                    parts.append(
                        f"pid={pid} display={disp} STATUS {st.get('status')} "
                        f"to={st.get('recipient_id')}"
                    )
            if not msgs and not stats:
                parts.append(f"pid={pid} display={disp} (empty change)")
    if parts:
        logger.info("whatsapp webhook batch: %s", " | ".join(parts))
    else:
        logger.info("whatsapp webhook batch: (no entry/changes)")


async def _try_claim_webhook_event(
    session: AsyncSession,
    *,
    provider_event_id: str,
    payload: dict,
) -> bool:
    """Insert the idempotency row; return False when another worker already claimed it."""
    try:
        async with session.begin_nested():
            session.add(
                WebhookEvent(
                    provider_event_id=provider_event_id,
                    payload=payload,
                    processed_at=datetime.now(timezone.utc),
                )
            )
            await session.flush()
        return True
    except IntegrityError:
        return False


async def _process_status_events(session: AsyncSession, payload: dict) -> None:
    """Mark outbox rows dead when Meta reports a delivery FAILURE for them.

    Best-effort: status handling must never block inbound message processing.
    sent/delivered/read events are ignored (no read-receipt feature — YAGNI).
    """
    from app.outbox.models import OutboxMessage
    from app.outbox.worker import _META_PERMANENT_CODES
    from app.webhook.normalizer import parse_status_events

    try:
        for ev in parse_status_events(payload):
            if ev["status"] != "failed" or not ev["wa_message_id"]:
                continue
            row = await session.scalar(
                select(OutboxMessage).where(
                    OutboxMessage.wa_message_id == ev["wa_message_id"]
                )
            )
            if row is None:
                logger.error(
                    "Meta reported delivery FAILURE for unknown message %s (code=%s)",
                    ev["wa_message_id"], ev["error_code"],
                )
                continue
            reason = _META_PERMANENT_CODES.get(ev["error_code"], "delivery_failed")
            row.status = "dead"
            row.payload = {**row.payload, "fail_reason": reason}
            logger.error(
                "outbound %s to %s failed after send (code=%s reason=%s) — marked dead",
                ev["wa_message_id"], row.to_phone, ev["error_code"], reason,
            )
        await session.commit()
    except Exception:
        await session.rollback()
        logger.error("status-event processing failed — continuing", exc_info=True)


async def _schedule_post_commit_delivery(
    session: AsyncSession,
    *,
    restaurant_id: int,
    claimed_ids: list[int],
    outbox_sync_delivery: bool,
) -> None:
    """Enqueue or deliver outbound replies after a successful webhook commit.

    Isolated from the main processing try/except so infra failures here never
    trigger the customer-facing error apology for a turn that already succeeded.
    """
    try:
        from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

        await flush_pending_partner_webhooks(session, restaurant_id=restaurant_id)
    except Exception:
        logger.error(
            "partner webhook scheduling failed for restaurant %s",
            restaurant_id,
            exc_info=True,
        )

    try:
        if outbox_sync_delivery:
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
                await _deliver_one(
                    outbox_id, provider=provider, session_factory=sync_factory
                )
        else:
            for outbox_id in claimed_ids:
                try:
                    deliver_outbox_message.apply_async(
                        args=[outbox_id], queue="outbox"
                    )
                except Exception:
                    logger.error(
                        "failed to enqueue outbox delivery for id=%s",
                        outbox_id,
                        exc_info=True,
                    )
    except Exception:
        logger.error(
            "outbox delivery scheduling failed for restaurant %s",
            restaurant_id,
            exc_info=True,
        )


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
