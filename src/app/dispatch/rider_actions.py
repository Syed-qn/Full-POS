"""Transport-agnostic rider delivery actions (spec §4.4.3-4.4.4).

The FSM/state transitions for a rider advancing a delivery — batch pickup,
delivered, COD collection, next-stop resolution — live here, decoupled from how
the rider triggers them (WhatsApp buttons or the native app) and how the result
is messaged back. Both transports call these functions and translate the
structured result into their own UI / messages.

What belongs here (transport-independent): the order/delivery FSM transitions,
COD recording, the customer-facing "delivered" notification (always WhatsApp to
the customer regardless of how the rider acted), and re-dispatch on batch
completion. What does NOT belong here: rider-facing messaging (stop nav, the
live-location prompt, "head back") — that's the calling transport's job.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.service import record_collection
from app.dispatch.delivery import advance_delivery
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Rider
from app.ordering.models import Order

_logger = logging.getLogger(__name__)


class PickupOutcome(str, Enum):
    PICKED_UP = "picked_up"          # batch advanced; first_order set
    NO_BATCH_RESEND = "no_batch_resend"  # mid-run, no new batch: re-send current stop
    NO_BATCH_NONE = "no_batch_none"      # nothing to pick up
    NO_STOPS = "no_stops"                # batch had no active stops


@dataclass
class PickupResult:
    outcome: PickupOutcome
    batch_id: int | None = None
    first_order: Order | None = None   # PICKED_UP: the first stop's order
    resend_order: Order | None = None  # NO_BATCH_RESEND: the stop to re-send


class DeliverOutcome(str, Enum):
    DELIVERED = "delivered"
    NOT_LIVE = "not_live"   # GPS sharing off → caller must prompt; nothing advanced
    IGNORED = "ignored"     # unknown / foreign order


@dataclass
class DeliverResult:
    outcome: DeliverOutcome
    order: Order | None = None
    next_order: Order | None = None  # DELIVERED: next undelivered stop, if any
    batch_id: int | None = None
    batch_complete: bool = False     # DELIVERED: last stop in the batch


async def mark_batch_picked_up(
    session: AsyncSession, *, restaurant_id: int, rider: Rider, batch_id: int | None
) -> PickupResult:
    """Advance the rider's batch to ``picked_up`` and every order to ``picked_up``.

    Resilient to a stale/invalid ``batch_id`` (reassigned batch, double-tap, test
    send): falls back to the rider's current planned batch. If there's no batch to
    pick up but the rider is mid-run, returns NO_BATCH_RESEND so the caller can
    re-send the current stop. Pure state transition — no rider messaging, and the
    customer's "on the way" notification is deliberately deferred to the first GPS
    ping (not here)."""
    batch = await session.get(Batch, batch_id) if batch_id else None
    if batch is None or batch.rider_id != rider.id or batch.status != "planned":
        batch = await session.scalar(
            select(Batch)
            .where(Batch.rider_id == rider.id, Batch.status == "planned")
            .order_by(Batch.id.desc())
            .limit(1)
        )
    if batch is None:
        bo = await session.scalar(
            select(BatchOrder)
            .join(Batch, BatchOrder.batch_id == Batch.id)
            .where(
                Batch.rider_id == rider.id,
                Batch.status == "picked_up",
                BatchOrder.delivered_at.is_(None),
            )
            .order_by(BatchOrder.sequence)
            .limit(1)
        )
        order = await session.get(Order, bo.order_id) if bo is not None else None
        if order is not None:
            return PickupResult(PickupOutcome.NO_BATCH_RESEND, resend_order=order)
        return PickupResult(PickupOutcome.NO_BATCH_NONE)

    batch.status = "picked_up"
    bos = (
        await session.scalars(
            select(BatchOrder)
            .where(BatchOrder.batch_id == batch.id)
            .order_by(BatchOrder.sequence)
        )
    ).all()
    first_order: Order | None = None
    for bo in bos:
        order = await session.get(Order, bo.order_id)
        if order is None:
            continue
        await advance_delivery(session, order_id=order.id, to_status="picked_up")
        if first_order is None:
            first_order = order
    if first_order is None:
        return PickupResult(PickupOutcome.NO_STOPS, batch_id=batch.id)
    return PickupResult(
        PickupOutcome.PICKED_UP, batch_id=batch.id, first_order=first_order
    )


async def mark_order_delivered(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider: Rider,
    order_id: int,
    cod_amount=None,
) -> DeliverResult:
    """Deliver one order, record COD, and resolve the next stop / batch completion.

    Gated on live GPS: if the rider isn't sharing location (no recent ping) the
    order is NOT advanced and NOT_LIVE is returned so the caller can prompt. On
    success: collapses ``arriving``, advances to ``delivered``, notifies the
    customer, records the COD cash (defaults to the order total — COD-only), then
    reports the next undelivered stop or batch completion (re-running dispatch when
    the rider is freed). Rider-facing messaging is the caller's job."""
    from app.dispatch.rider_flow import _notify_customer_status, _rider_tracker_is_live

    order = await session.get(Order, order_id)
    if order is None or order.rider_id != rider.id:
        return DeliverResult(DeliverOutcome.IGNORED)
    if not await _rider_tracker_is_live(session, rider.id):
        return DeliverResult(DeliverOutcome.NOT_LIVE, order=order)

    if order.status == "picked_up":
        await advance_delivery(session, order_id=order.id, to_status="arriving")
    await advance_delivery(session, order_id=order.id, to_status="delivered")
    await _notify_customer_status(
        session, restaurant_id=restaurant_id, order=order, status_key="delivered"
    )
    await record_collection(
        session,
        restaurant_id=restaurant_id,
        order_id=order.id,
        rider_id=rider.id,
        amount=order.total if cod_amount is None else cod_amount,
    )

    bo = await session.scalar(select(BatchOrder).where(BatchOrder.order_id == order.id))
    if bo is None:
        return DeliverResult(DeliverOutcome.DELIVERED, order=order)
    remaining = (
        await session.scalars(
            select(BatchOrder)
            .where(
                BatchOrder.batch_id == bo.batch_id,
                BatchOrder.delivered_at.is_(None),
            )
            .order_by(BatchOrder.sequence)
        )
    ).all()
    if remaining:
        nxt = await session.get(Order, remaining[0].order_id)
        return DeliverResult(
            DeliverOutcome.DELIVERED, order=order, next_order=nxt, batch_id=bo.batch_id
        )

    # Batch complete: the rider was just freed (status -> available in
    # delivery._complete_batch_order). Re-run dispatch so orders left waiting in
    # ``ready`` (no rider was free when they became ready) get picked up now —
    # production has no Celery beat sweeper (CLAUDE.md). Best-effort: a dispatch
    # error must never undo the delivery just recorded.
    from app.dispatch.service import run_dispatch_engine

    try:
        await run_dispatch_engine(session, restaurant_id=restaurant_id)
    except Exception:  # noqa: BLE001 - re-dispatch must not break delivery
        _logger.exception(
            "re-dispatch after freeing rider %s failed (restaurant_id=%s)",
            rider.id,
            restaurant_id,
        )
    return DeliverResult(
        DeliverOutcome.DELIVERED, order=order, batch_id=bo.batch_id, batch_complete=True
    )
