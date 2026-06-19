"""Rider button-driven delivery flow (spec §4.4.3-4.4.4).

The rider's WhatsApp buttons are the ONLY way to advance the delivery and to
reveal the next stop (flow integrity):

  * ``picked:{batch_id}``  -> mark the batch ``picked_up``, advance every order
    ``assigned -> picked_up``, then send the FIRST stop nav with a Delivered
    (COD: "Collect money & delivered") button.
  * ``delivered:{order_id}`` -> collapse ``arriving`` and advance the order to
    ``delivered``, record the COD cash (COD-only platform), then send the NEXT
    stop nav or a "head back to the restaurant" message when the batch is done.

Drop-off coordinates come from the order's CustomerAddress (orders carry no
dropoff_lat/lon columns); the nav link is omitted gracefully when absent.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.service import record_collection
from app.dispatch.delivery import advance_delivery
from app.dispatch.models import Batch, BatchOrder, RiderLocation
from app.geo.haversine import distance_km
from app.identity.models import Rider
from app.ordering.models import Customer, CustomerAddress, Order
from app.outbox.models import OutboxMessage
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType

_logger = logging.getLogger(__name__)


async def _notify_customer_status(
    session: AsyncSession, *, restaurant_id: int, order: Order, status_key: str
) -> None:
    """Proactively message the customer when delivery progresses (picked_up → on
    the way, delivered). Idempotent per (order, status) so a rider double-tap or
    an outbox re-delivery never double-pings the customer. The customer's 24h
    window is open (they ordered minutes ago), so a free-form text delivers — no
    template needed (unlike the rider side). Reuses build_tracking_reply so the
    wording (and live ETA when a GPS ping exists) matches the "where's my order"
    reply."""
    from app.dispatch.tracking import build_tracking_reply
    from app.geo.factory import get_geo_provider

    if order.customer_id is None:
        return
    key = f"cust-{status_key}-{order.id}"
    if await session.scalar(
        select(OutboxMessage.id).where(OutboxMessage.idempotency_key == key)
    ) is not None:
        return  # already notified for this order+status
    customer = await session.get(Customer, order.customer_id)
    if customer is None or not customer.phone:
        return
    body = await build_tracking_reply(session, order=order, geo=get_geo_provider())
    if status_key == "picked_up":
        from app.dispatch.tracking_live import build_tracking_url, ensure_tracking_session

        tracking = await ensure_tracking_session(session, order=order)
        # Hand the customer a tappable "Track your rider" button (CTA URL) instead
        # of a raw link — mirrors the rider's "Start live tracker" button. The
        # customer ordered minutes ago, so their 24h window is open and a free-form
        # interactive button delivers without a pre-approved template.
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=customer.phone,
            msg_type=OutboundMessageType.CTA_URL,
            payload={
                "body": f"{body}\n\nTrack your order live on the map below.",
                "button_label": "Track my order",
                "url": build_tracking_url(tracking.tracking_token),
            },
            idempotency_key=key,
        )
        return
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=customer.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
        idempotency_key=key,
    )

# ~100 m per spec §4.4 + transcript (geofence worker). Button click ONLY way to reveal next location (flow integrity).
NEAR_KM = 0.1
# Power bank + constant power supply provided per ops policy for all-day live location sharing.


def _maps_link(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}"


async def _dropoff_coords(
    session: AsyncSession, order: Order
) -> tuple[float, float] | None:
    if order.address_id is None:
        return None
    addr = await session.get(CustomerAddress, order.address_id)
    if addr is None or addr.latitude is None or addr.longitude is None:
        return None
    return (addr.latitude, addr.longitude)


async def _stop_details(
    session: AsyncSession, order: Order
) -> tuple[str, str, tuple[float, float] | None]:
    """Gather the rider-facing delivery details: customer name, a readable
    address, and drop-off coordinates (only present for orders placed with a
    WhatsApp location pin)."""
    name = ""
    address_str = ""
    coords: tuple[float, float] | None = None
    if order.customer_id:
        cust = await session.get(Customer, order.customer_id)
        if cust and cust.name:
            name = cust.name
    if order.address_id:
        addr = await session.get(CustomerAddress, order.address_id)
        if addr:
            if not name and addr.receiver_name:
                name = addr.receiver_name
            parts = [
                p for p in (addr.room_apartment, addr.building, addr.additional_details) if p
            ]
            address_str = ", ".join(parts)
            if addr.latitude is not None and addr.longitude is not None:
                coords = (addr.latitude, addr.longitude)
    return name, address_str, coords


def _stop_body(
    order: Order,
    name: str,
    address_str: str,
    coords: tuple[float, float] | None,
    *,
    near: bool = False,
) -> str:
    """Beautified WhatsApp message for the rider's current stop (bold labels,
    name / address / COD amount, and a tappable Map link when coordinates exist)."""
    head = "Near stop" if near else "Next stop"
    lines = [f"🛵 *{head} — Order {order.order_number}*", ""]
    if name:
        lines.append(f"👤 *Name:* {name}")
    if address_str:
        lines.append(f"📍 *Address:* {address_str}")
    if order.total:
        lines.append(f"💵 *Collect (COD):* AED {order.total:.2f}")
    if near:
        lines.append("\nYou're close — choose below once delivered.")
    return "\n".join(lines)


async def _send_map_button(
    session: AsyncSession,
    restaurant_id: int,
    rider_phone: str,
    order: Order,
    coords: tuple[float, float],
    *,
    key_suffix: str = "",
) -> None:
    """Send a tappable “Open in Maps” URL button for this stop. Sent as its own
    message because WhatsApp can't mix a URL button with the Delivered quick-reply
    button. Only called when the order has drop-off coordinates (WhatsApp orders)."""
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=rider_phone,
        msg_type=OutboundMessageType.CTA_URL,
        payload={
            "body": f"🗺️ Navigation for Order {order.order_number}",
            "button_label": "Open in Maps",
            "url": _maps_link(*coords),
        },
        idempotency_key=f"map-{order.id}{key_suffix}",
    )


async def _send_live_location_request(
    session: AsyncSession, restaurant_id: int, rider_phone: str, batch_id: int
) -> None:
    """Ask the rider to start sharing live location for this run.

    WhatsApp gives no API to switch live location on — the rider must tap it in
    their app — so this is an instructional text. We suggest the 1-hour option
    (comfortably covers the 40-min SLA) and it expires on its own afterwards, so
    there's no "turn it off" step. Idempotent per batch."""
    body = (
        "📍 *Share your live location* so we can track this delivery.\n\n"
        "Tap *Start live tracker* below, allow GPS, and keep the page open. "
        "You must start it before you can mark a stop delivered.\n\n"
        "It stops automatically when the delivery ends."
    )
    first_order = await session.scalar(
        select(Order)
        .join(BatchOrder, BatchOrder.order_id == Order.id)
        .where(BatchOrder.batch_id == batch_id)
        .order_by(BatchOrder.sequence)
        .limit(1)
    )
    if first_order is not None and first_order.rider_id is not None:
        from app.dispatch.tracking_live import (
            build_rider_tracking_url,
            ensure_tracking_session,
        )

        tracking = await ensure_tracking_session(session, order=first_order)
        # Tappable button (CTA URL) instead of a raw link. The rider just tapped
        # "Orders Picked", so their 24h window is open and a free-form interactive
        # button delivers without a pre-approved template.
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=rider_phone,
            msg_type=OutboundMessageType.CTA_URL,
            payload={
                "body": body,
                "button_label": "Start live tracker",
                "url": build_rider_tracking_url(tracking.rider_token),
            },
            idempotency_key=f"livereq-{batch_id}",
        )
        return
    # No order/rider resolved — still send the instruction (no button to attach).
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=rider_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
        idempotency_key=f"livereq-{batch_id}",
    )


async def handle_orders_picked(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider: Rider,
    batch_id: int | None,
    trigger_msg_id: str | None = None,
) -> None:
    """Rider pressed "Orders Picked": advance the whole batch and send stop #1.

    Resilient to a stale/invalid ``batch_id`` (a reassigned batch, a double-tap,
    a test send): fall back to the rider's current planned batch so the tap still
    works, and always reply — never a silent no-op (which reads to the rider as
    "the button is broken")."""
    batch = await session.get(Batch, batch_id) if batch_id else None
    if batch is None or batch.rider_id != rider.id or batch.status != "planned":
        # Use the rider's current planned batch instead of trusting the payload.
        batch = await session.scalar(
            select(Batch)
            .where(Batch.rider_id == rider.id, Batch.status == "planned")
            .order_by(Batch.id.desc())
            .limit(1)
        )
    if batch is None:
        # No new batch to pick up. The rider may already be mid-run and just
        # never received (or lost) their current stop — re-send it so tapping
        # again recovers it. Otherwise tell them there's nothing to pick up.
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
            # Unique suffix so the re-send isn't deduped against the original stop.
            await _send_stop(session, restaurant_id, rider.phone, order,
                             key_suffix=f"-resend-{trigger_msg_id or 'x'}")
        else:
            await enqueue_message(
                session,
                restaurant_id=restaurant_id,
                to_phone=rider.phone,
                msg_type=OutboundMessageType.TEXT,
                payload={"body": "You have no active batch to pick up right now. "
                                 "We'll message you when one is assigned."},
                idempotency_key=f"nopick-{trigger_msg_id or rider.id}",
            )
        return
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
        # Proactively tell the customer their order is on the way.
        await _notify_customer_status(
            session, restaurant_id=restaurant_id, order=order, status_key="picked_up"
        )
        if first_order is None:
            first_order = order
    if first_order is not None:
        # Prompt live-location sharing for the run (sent before the stop so the
        # Delivered-button message stays the rider's latest/most-actionable msg).
        await _send_live_location_request(
            session, restaurant_id, rider.phone, batch.id
        )
        await _send_stop(session, restaurant_id, rider.phone, first_order)
    else:
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=rider.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "That batch has no active stops left."},
            idempotency_key=f"nostop-{trigger_msg_id or batch.id}",
        )


# Live tracking must be ON when a stop is delivered. A ping within this window
# means the rider's tracker page is open and sharing GPS (it posts every ~5s).
_TRACKER_LIVE_WINDOW_MIN = 15


async def _rider_tracker_is_live(session: AsyncSession, rider_id: int) -> bool:
    """True if the rider has shared a GPS ping recently (tracker page is open)."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=_TRACKER_LIVE_WINDOW_MIN)
    row = await session.scalar(
        select(RiderLocation.id)
        .where(RiderLocation.rider_id == rider_id, RiderLocation.ts >= cutoff)
        .limit(1)
    )
    return row is not None


async def _send_start_tracker_required(
    session: AsyncSession, restaurant_id: int, rider: Rider, order: Order,
    trigger_msg_id: str | None,
) -> None:
    """Re-send the Start-live-tracker button when the rider tries to deliver
    without GPS sharing on. Uses the run's shared tracker (the batch's first
    order session) so it's the same page they were given at pickup."""
    from app.dispatch.tracking_live import build_rider_tracking_url, ensure_tracking_session

    first = order
    bo = await session.scalar(select(BatchOrder).where(BatchOrder.order_id == order.id))
    if bo is not None:
        fo = await session.scalar(
            select(Order)
            .join(BatchOrder, BatchOrder.order_id == Order.id)
            .where(BatchOrder.batch_id == bo.batch_id)
            .order_by(BatchOrder.sequence)
            .limit(1)
        )
        if fo is not None:
            first = fo
    tracking = await ensure_tracking_session(session, order=first)
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=rider.phone,
        msg_type=OutboundMessageType.CTA_URL,
        payload={
            "body": "⚠️ *Start the live tracker first.*\nTap below, allow GPS, and keep "
                    "the page open — then tap *Delivered* again.",
            "button_label": "Start live tracker",
            "url": build_rider_tracking_url(tracking.rider_token),
        },
        idempotency_key=f"tracker-required-{order.id}-{trigger_msg_id or rider.id}",
    )


async def handle_delivered(
    session: AsyncSession, *, restaurant_id: int, rider: Rider, order_id: int,
    trigger_msg_id: str | None = None,
) -> None:
    """Rider pressed "Delivered": finish this order + record COD + send next stop.

    Gated on live tracking: the rider must have GPS sharing on (a recent ping)
    before a stop can be marked delivered. If not, re-send the tracker button and
    do NOT advance the order."""
    order = await session.get(Order, order_id)
    if order is None or order.rider_id != rider.id:
        return
    if not await _rider_tracker_is_live(session, rider.id):
        await _send_start_tracker_required(
            session, restaurant_id, rider, order, trigger_msg_id
        )
        return
    # Collapse the geofence "arriving" step on the rider's physical confirmation.
    if order.status == "picked_up":
        await advance_delivery(session, order_id=order.id, to_status="arriving")
    await advance_delivery(session, order_id=order.id, to_status="delivered")
    # Proactively tell the customer their order has been delivered.
    await _notify_customer_status(
        session, restaurant_id=restaurant_id, order=order, status_key="delivered"
    )
    # COD-only platform: every delivery collects the order total in cash.
    await record_collection(
        session,
        restaurant_id=restaurant_id,
        order_id=order.id,
        rider_id=rider.id,
        amount=order.total,
    )
    # Reveal the next stop, or signal the run is complete.
    bo = await session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == order.id)
    )
    if bo is None:
        return
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
        if nxt is not None:
            await _send_stop(session, restaurant_id, rider.phone, nxt)
    else:
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=rider.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": "All delivered. Head back to the restaurant."},
            idempotency_key=f"headback-{bo.batch_id}-{rider.id}",
        )
        # The batch is complete and the rider was just freed (status -> available
        # in delivery._complete_batch_order). Re-run dispatch so any orders left
        # waiting in `ready` (no rider was available when they became ready) are
        # picked up immediately, instead of sitting until the next order hits
        # `ready`. Production has no Celery beat sweeper (see CLAUDE.md), so a
        # freed rider would otherwise never trigger a re-scan on its own. The
        # rider-assignment + customer pushes this enqueues are delivered by the
        # webhook's restaurant-wide outbox claim after this transaction commits.
        # Best-effort: a dispatch error must never undo the delivery just recorded.
        from app.dispatch.service import run_dispatch_engine

        try:
            await run_dispatch_engine(session, restaurant_id=restaurant_id)
        except Exception:  # noqa: BLE001 - re-dispatch must not break delivery
            _logger.exception(
                "re-dispatch after freeing rider %s failed (restaurant_id=%s)",
                rider.id,
                restaurant_id,
            )


async def _get_latest_rider_location(session: AsyncSession, rider_id: int) -> tuple[float, float] | None:
    loc = await session.scalar(
        select(RiderLocation).where(RiderLocation.rider_id == rider_id).order_by(RiderLocation.ts.desc()).limit(1)
    )
    if loc:
        return (loc.latitude, loc.longitude)
    return None


async def _send_stop(
    session: AsyncSession, restaurant_id: int, rider_phone: str, order: Order,
    *, force_next: bool = False, key_suffix: str = "",
) -> None:
    """Send the rider the next stop: nav link + Delivered button (COD-aware).
    If near (~100m) or force_next, send dual buttons per spec §4.4 (button click mandatory for next location).
    Include customer contact for rider (name); customer side uses "Message rider" button (no raw phone leak).
    ``key_suffix`` makes the idempotency key unique for an intentional re-send
    (e.g. rider re-tapped because the first stop message was lost).
    """
    name, address_str, coords = await _stop_details(session, order)
    title = "Collect & delivered" if order.total else "Delivered"
    body = _stop_body(order, name, address_str, coords, near=force_next)
    buttons = [{"id": f"delivered:{order.id}", "title": title}]
    # dual if near or force (for delivered_next path)
    if force_next:
        buttons.append({"id": f"delivered_next:{order.id}", "title": "Delivered & next"})
    # Map button first so the details+Delivered message stays the latest send.
    if coords:
        await _send_map_button(
            session, restaurant_id, rider_phone, order, coords, key_suffix=key_suffix
        )
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=rider_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={"body": body, "buttons": buttons},
        idempotency_key=f"stop-{order.id}{key_suffix}",
    )


async def check_and_send_near_dual_if_applicable(
    session: AsyncSession, *, restaurant_id: int, rider: Rider
) -> None:
    """Geofence check on location ping: if rider within ~100m of current undelivered stop, send dual buttons.
    Called from engine after rider LOCATION inbound. Power bank policy note above.
    """
    # find active batch + first undelivered order for this rider
    bo = await session.scalar(
        select(BatchOrder)
        .join(Batch, BatchOrder.batch_id == Batch.id)
        .where(Batch.rider_id == rider.id, BatchOrder.delivered_at.is_(None))
        .order_by(BatchOrder.sequence)
        .limit(1)
    )
    if not bo:
        return
    order = await session.get(Order, bo.order_id)
    if not order:
        return
    pos = await _get_latest_rider_location(session, rider.id)
    drop = await _dropoff_coords(session, order)
    if pos and drop and distance_km(*pos, *drop) <= NEAR_KM:
        await _send_stop(session, restaurant_id, rider.phone, order)  # will send dual if we enhance _send_stop
        # for dual, enhance call or separate; here for TDD we will adjust _send_stop to check near again or pass flag
        # simple: always send dual in this path for test (refine later)
        # to match: call a dual sender
        await _send_delivery_choice(session, restaurant_id, rider.phone, order)


async def _send_delivery_choice(
    session: AsyncSession, restaurant_id: int, rider_phone: str, order: Order
) -> None:
    """Dual buttons when near per spec/transcript."""
    name, address_str, coords = await _stop_details(session, order)
    title = "Collect & delivered" if order.total else "Delivered"
    body = _stop_body(order, name, address_str, coords, near=True)
    buttons = [
        {"id": f"delivered:{order.id}", "title": title},
        {"id": f"delivered_next:{order.id}", "title": "Delivered & next"},
    ]
    # No map button here: in the near flow this runs right after _send_stop in
    # the same transaction, which already enqueued the map button for this order.
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=rider_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={"body": body, "buttons": buttons},
        idempotency_key=f"choice-{order.id}",
    )
