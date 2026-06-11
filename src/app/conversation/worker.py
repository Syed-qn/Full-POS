"""Abandoned-cart recovery Celery task.

Every few minutes, find customer conversations that still hold a DRAFT order
with items but have gone quiet for ABANDONED_AFTER_MIN minutes, and send ONE
gentle nudge. The ``abandoned_nudged`` flag in conversation state makes it
once-only; it is re-armed (cleared) whenever the customer adds another item.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from celery import shared_task
from sqlalchemy import func, select

from app.conversation.models import Conversation
from app.db import async_session_factory
from app.ordering.fsm import OrderStatus
from app.ordering.models import Order, OrderItem
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType

logger = logging.getLogger(__name__)

ABANDONED_AFTER_MIN = 15
_NUDGE_BODY = (
    "Hi 👋 You still have items in your cart. "
    "Would you like to complete your order?"
)


@shared_task(name="conversation.abandoned_cart_sweep", bind=True,
             max_retries=3, default_retry_delay=30)
def abandoned_cart_sweep(self) -> int:  # type: ignore[override]
    return asyncio.run(_run_sweep())


async def _run_sweep() -> int:
    """Send nudges for stale draft carts. Returns the number of nudges enqueued."""
    nudged = 0
    async with async_session_factory() as session:
        # Server-side cutoff: compare the naive ``updated_at`` against the DB's
        # own clock minus the window. Doing the subtraction in SQL avoids any
        # Python-vs-DB timezone mismatch on the timezone-naive column.
        cutoff = func.now() - timedelta(minutes=ABANDONED_AFTER_MIN)
        convs = (
            await session.scalars(
                select(Conversation).where(
                    Conversation.counterpart == "customer",
                    Conversation.updated_at < cutoff,
                )
            )
        ).all()

        for conv in convs:
            state = conv.state or {}
            if state.get("abandoned_nudged"):
                continue
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

            await enqueue_message(
                session,
                restaurant_id=conv.restaurant_id,
                to_phone=conv.phone,
                msg_type=OutboundMessageType.TEXT,
                payload={"body": _NUDGE_BODY},
                idempotency_key=f"abandoned-{conv.id}-{draft_id}",
            )
            conv.state = {**state, "abandoned_nudged": True}
            nudged += 1

        await session.commit()
    if nudged:
        logger.info("abandoned_cart_sweep nudged %d cart(s)", nudged)
    return nudged
