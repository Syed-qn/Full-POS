"""Abandoned-cart recovery Celery task.

Every few minutes, look at customer conversations that still hold a DRAFT order
with items and have gone quiet. Behaviour is per-restaurant (Settings page):

* ``cart_reminder_enabled`` — send ONE gentle nudge after ``cart_recovery_minutes``
  of silence. The ``abandoned_nudged`` state flag keeps it once-only; it is re-armed
  whenever the customer touches the cart again.
* ``cart_expiry_minutes`` — once a cart has been quiet this long, auto-CLEAR it
  (drop its items, zero the totals, drop the draft pointer) so stale carts don't
  pile up or silently resurface in a later order.
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from celery import shared_task
from sqlalchemy import delete as sa_delete
from sqlalchemy import select, text

from app.conversation.models import Conversation
from app.db import async_session_factory
from app.identity.models import Restaurant
from app.ordering.fsm import OrderStatus
from app.ordering.models import Order, OrderItem
from app.outbox.service import deliver_outbox_now, enqueue_message
from app.whatsapp.port import OutboundMessageType

logger = logging.getLogger(__name__)

# Fallbacks when a restaurant row predates the cart settings.
ABANDONED_AFTER_MIN = 15
DEFAULT_EXPIRY_MIN = 60
# Fallback nudge when the cart can't be rendered (no items resolved). The normal
# nudge shows the cart contents + a concrete next step instead of a dead-end yes/no
# — a bare "would you like to complete your order?" leaves the bot unable to act on
# a "Yes", which dead-ends the flow.
_NUDGE_BODY = (
    "Hi 👋 You still have items in your cart. "
    "Say *done* whenever you're ready to check out, or tell me what else to add 😊"
)


@shared_task(name="conversation.abandoned_cart_sweep", bind=True,
             max_retries=3, default_retry_delay=30)
def abandoned_cart_sweep(self) -> int:  # type: ignore[override]
    return asyncio.run(_run_sweep())


async def _run_sweep() -> int:
    """Nudge and/or auto-clear stale draft carts. Returns the number of nudges sent."""
    nudged = 0
    cleared = 0
    nudge_ids: list[int] = []
    async with async_session_factory() as session:
        # Let the DB compute "quiet minutes" from its own clock so we never trip on a
        # Python-vs-DB timezone mismatch on the naive ``updated_at`` column.
        rows = (
            await session.execute(
                text(
                    "SELECT id, restaurant_id, state, "
                    "EXTRACT(EPOCH FROM (now() - updated_at)) / 60.0 AS quiet_min "
                    "FROM conversations WHERE counterpart = 'customer'"
                )
            )
        ).all()

        settings_cache: dict[int, dict] = {}
        for row in rows:
            state = row.state or {}
            draft_id = state.get("draft_order_id")
            if not draft_id:
                continue
            order = await session.get(Order, draft_id)
            if order is None or str(order.status) != str(OrderStatus.DRAFT):
                continue
            has_items = await session.scalar(
                select(OrderItem.id).where(OrderItem.order_id == order.id).limit(1)
            )
            if not has_items:
                continue

            settings = settings_cache.get(row.restaurant_id)
            if settings is None:
                rest = await session.get(Restaurant, row.restaurant_id)
                settings = (rest.settings or {}) if rest is not None else {}
                settings_cache[row.restaurant_id] = settings
            recovery_min = int(settings.get("cart_recovery_minutes", ABANDONED_AFTER_MIN))
            expiry_min = int(settings.get("cart_expiry_minutes", DEFAULT_EXPIRY_MIN))
            reminder_on = bool(settings.get("cart_reminder_enabled", True))
            quiet = float(row.quiet_min or 0.0)

            conv = await session.get(Conversation, row.id)
            if conv is None:
                continue

            # 1) Expired → clear the cart (drop items, zero totals, drop the pointer).
            if quiet >= expiry_min:
                await session.execute(
                    sa_delete(OrderItem).where(OrderItem.order_id == order.id)
                )
                order.subtotal = Decimal("0.00")
                order.total = order.delivery_fee_aed
                st = dict(conv.state or {})
                for key in ("draft_order_id", "pending_order_id", "abandoned_nudged"):
                    st.pop(key, None)
                conv.state = st
                cleared += 1
                continue

            # 2) Quiet long enough → one-time nudge (if the restaurant enabled it).
            # ``quiet`` is recomputed by the DB at the top of every sweep, so a
            # customer who came back since the last sweep already shows a small quiet
            # value and won't qualify — that's the re-engagement guard.
            if reminder_on and quiet >= recovery_min and not state.get("abandoned_nudged"):
                # Show the actual cart + a concrete next step, not a dead-end yes/no.
                from app.conversation.engine import _build_cart_summary

                cart = await _build_cart_summary(session, conv)
                body = (
                    "Hi 👋 You still have items in your cart:\n\n"
                    f"🛒 {cart}\n\n"
                    "Say *done* whenever you're ready to check out, "
                    "or tell me anything else you'd like to add 😊"
                ) if cart else _NUDGE_BODY
                # Key per NUDGE, not just per cart: outbox.idempotency_key is unique,
                # so a bare "abandoned-{conv}-{draft}" can be sent only once ever — a
                # re-armed cart (customer came back, then went quiet again) would
                # collide and silently fail. A monotonic per-cart counter gives each
                # nudge a fresh key; the once-only "abandoned_nudged" flag still
                # prevents double-sends within a single quiet cycle.
                seq = int((conv.state or {}).get("abandoned_nudge_count", 0)) + 1
                row = await enqueue_message(
                    session,
                    restaurant_id=conv.restaurant_id,
                    to_phone=conv.phone,
                    msg_type=OutboundMessageType.TEXT,
                    payload={"body": body},
                    idempotency_key=f"abandoned-{conv.id}-{draft_id}-{seq}",
                )
                await session.flush()  # assign row.id before we record it for delivery
                nudge_ids.append(row.id)
                conv.state = {
                    **(conv.state or {}),
                    "abandoned_nudged": True,
                    "abandoned_nudge_count": seq,
                }
                nudged += 1

        await session.commit()
        # enqueue_message only writes a pending row. This is a background task (no
        # request to flush it), so we must deliver explicitly — otherwise the nudge
        # sits pending forever on Render (sync delivery) where no outbox queue runs.
        if nudge_ids:
            await deliver_outbox_now(session, nudge_ids)
    if nudged or cleared:
        logger.info("abandoned_cart_sweep nudged %d, cleared %d cart(s)", nudged, cleared)
    return nudged
