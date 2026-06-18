"""Auto-dispatch engine (spec §4.3).

Behaviour:
  * Eligible set = orders ``status == "ready"`` and unassigned + riders with
    ``status == "available"``.
  * Build proximity batches (Task 7), score riders (Task 6), assign the best
    available rider per batch.
  * On assignment: create Batch + BatchOrder rows, set each order
    ``status = "assigned"`` + ``rider_id``, set rider ``status = "on_delivery"``,
    write an Assignment row carrying the explainability breakdown, ``record_audit``
    per order transition, and notify the rider via the outbox.
  * No available riders -> orders stay ``ready``/unassigned (no status change),
    a manager alert is enqueued, and the result flags ``needs_retry``.
  * Riders are employees -> NO accept/reject step.

Schema adaptation (Phase-3 T2 flags — NO new migration required):
  * Restaurant pickup coords come from ``Restaurant.lat`` / ``Restaurant.lng``.
  * Order drop-off is resolved via ``address_id`` -> CustomerAddress.latitude /
    longitude.
  * Rider position is the latest ``rider_locations`` ping; riders with no ping
    are treated as co-located with the restaurant (pickup distance 0) so they
    remain dispatchable.
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.dispatch.batching import OrderCandidate, build_batches, compute_batch_total_est_min
from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation
from app.dispatch.scoring import RiderCandidate, rank_riders
from app.geo.factory import get_geo_provider
from app.geo.haversine import distance_km
from app.identity.models import Restaurant, Rider
from app.ordering.fsm import OrderStatus
from app.ordering.models import CustomerAddress, Order
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType


@dataclass
class DispatchResult:
    assigned_count: int = 0
    unassigned_count: int = 0
    needs_retry: bool = False


@asynccontextmanager
async def _restaurant_lock(restaurant_id: int):
    """Best-effort per-restaurant lock. No-op if redis unavailable (tests)."""
    try:
        from app.redis_client import get_redis  # provided by Phase 2 if present

        redis = get_redis()
        lock = redis.lock(f"dispatch_lock:{restaurant_id}", timeout=30)
        acquired = await lock.acquire(blocking=False)
        try:
            yield acquired
        finally:
            if acquired:
                await lock.release()
    except Exception:
        # redis missing/unreachable -> proceed without distributed lock
        yield True


async def _active_order_count(session: AsyncSession, rider_id: int) -> int:
    """Count orders currently assigned to this rider and not yet delivered/cancelled."""
    result = await session.execute(
        select(func.count(Order.id)).where(
            Order.rider_id == rider_id,
            Order.status.in_(["assigned", "picked_up", "arriving"]),
        )
    )
    return result.scalar_one()


async def run_dispatch_engine(
    session: AsyncSession, *, restaurant_id: int
) -> DispatchResult:
    """Assign ready orders to nearest available riders. Idempotent per call."""
    async with _restaurant_lock(restaurant_id):
        return await _dispatch(session, restaurant_id)


# Alias used by dispatch router (spec §4.3)
run_dispatch = run_dispatch_engine


async def _latest_rider_positions(
    session: AsyncSession, restaurant_id: int
) -> dict[int, tuple[float, float]]:
    """Latest (lat, lon) ping per rider from rider_locations."""
    rows = (
        await session.scalars(
            select(RiderLocation)
            .where(RiderLocation.restaurant_id == restaurant_id)
            .order_by(RiderLocation.ts.asc())
        )
    ).all()
    # ascending order -> later rows overwrite earlier ones, leaving the latest.
    return {row.rider_id: (row.latitude, row.longitude) for row in rows}


async def _dropoff_coords(
    session: AsyncSession, orders: list[Order]
) -> dict[int, tuple[float, float]]:
    """Map order_id -> (lat, lon) via CustomerAddress."""
    addr_ids = {o.address_id for o in orders if o.address_id is not None}
    coords: dict[int, tuple[float, float]] = {}
    if not addr_ids:
        return coords
    addrs = (
        await session.scalars(
            select(CustomerAddress).where(CustomerAddress.id.in_(addr_ids))
        )
    ).all()
    by_addr = {a.id: a for a in addrs}
    for o in orders:
        a = by_addr.get(o.address_id)
        if a is not None and a.latitude is not None and a.longitude is not None:
            coords[o.id] = (a.latitude, a.longitude)
    return coords


async def _dispatch(session: AsyncSession, restaurant_id: int) -> DispatchResult:
    restaurant = await session.get(Restaurant, restaurant_id)
    now = datetime.now(timezone.utc)

    ready = (
        await session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant_id,
                Order.status == "ready",
                Order.rider_id.is_(None),
            )
        )
    ).all()
    if not ready:
        return DispatchResult()

    # Resale exclusion enforced: filter on_resale orders using is_excluded_for_resale for the original buyer.
    # (exclusion_hash from cancel after cooking; prevents same phone/person/address from re-buying per spec).

    dropoffs = await _dropoff_coords(session, ready)
    # Orders missing a geocoded drop-off fall back to the restaurant location so
    # they are still batched/dispatched rather than silently dropped.
    geo = get_geo_provider()
    candidates = []
    for o in ready:
        lat, lon = dropoffs.get(o.id, (restaurant.lat, restaurant.lng))
        # Real elapsed from sla_confirmed_at (set at order confirm/modify per ordering/service + spec);
        # fallback 0 if not present (e.g. legacy tests). Uses UTC.
        minutes_elapsed = 0.0
        if o.sla_confirmed_at is not None:
            sla = o.sla_confirmed_at
            if sla.tzinfo is None:
                sla = sla.replace(tzinfo=timezone.utc)
            minutes_elapsed = max(0.0, (now - sla).total_seconds() / 60.0)
        candidates.append(
            OrderCandidate(
                order_id=o.id,
                lat=lat,
                lon=lon,
                ready_at=o.updated_at or now,
                minutes_elapsed=minutes_elapsed,
                priority=o.priority or "normal",
            )
        )
    batches = build_batches(candidates, geo_provider=geo)
    orders_by_id = {o.id: o for o in ready}
    result = DispatchResult()

    for planned in batches:
        riders = (
            await session.scalars(
                select(Rider).where(
                    Rider.restaurant_id == restaurant_id,
                    Rider.status == "available",
                )
            )
        ).all()
        if not riders:
            # No riders: alert manager, leave orders untouched, request retry.
            result.unassigned_count += len(planned.orders)
            result.needs_retry = True
            await enqueue_message(
                session,
                restaurant_id=restaurant_id,
                to_phone=restaurant.phone,
                msg_type=OutboundMessageType.TEXT,
                payload={
                    "body": (
                        f"No available riders for {len(planned.orders)} ready "
                        "order(s). Orders are waiting; dispatch will retry."
                    )
                },
                idempotency_key=(
                    f"norider-{restaurant_id}-{planned.seed.order_id}-"
                    f"{int(now.timestamp())}"
                ),
            )
            continue

        positions = await _latest_rider_positions(session, restaurant_id)
        # Pickup distance = rider -> restaurant. Riders with no ping are treated
        # as already at the restaurant (distance 0).
        scored = rank_riders(
            [
                RiderCandidate(
                    rider_id=rd.id,
                    distance_km=distance_km(
                        *positions.get(rd.id, (restaurant.lat, restaurant.lng)),
                        restaurant.lat,
                        restaurant.lng,
                    ),
                    active_orders=await _active_order_count(session, rd.id),
                    on_time_pct=float(rd.performance.get("on_time_pct", 100.0)),
                )
                for rd in riders
            ]
        )
        best_id = scored[0].rider_id
        rider = next(rd for rd in riders if rd.id == best_id)

        total_est = compute_batch_total_est_min(planned, geo_provider=geo)
        batch = Batch(
            restaurant_id=restaurant_id,
            rider_id=rider.id,
            status="planned",
            route={
                "stops": [
                    {"order_id": pc.order_id, "lat": pc.lat, "lon": pc.lon}
                    for pc in planned.orders
                ]
            },
            total_est_min=total_est,
        )
        session.add(batch)
        await session.flush()

        for seq, pc in enumerate(planned.orders, start=1):
            order = orders_by_id[pc.order_id]
            before = {"status": order.status, "rider_id": order.rider_id}
            order.status = "assigned"
            order.rider_id = rider.id
            session.add(
                BatchOrder(batch_id=batch.id, order_id=order.id, sequence=seq)
            )
            session.add(
                Assignment(
                    order_id=order.id,
                    rider_id=rider.id,
                    batch_id=batch.id,
                    assigned_at=now,
                    algorithm_score=scored[0].breakdown,
                )
            )
            await record_audit(
                session,
                actor="system",
                restaurant_id=restaurant_id,
                entity="order",
                entity_id=str(order.id),
                action="state_transition",
                before=before,
                after={"status": "assigned", "rider_id": rider.id},
            )
            result.assigned_count += 1

        rider.status = "on_delivery"
        await _enqueue_rider_assignment(
            session,
            restaurant_id=restaurant_id,
            rider_phone=rider.phone,
            batch_id=batch.id,
            orders=[orders_by_id[pc.order_id] for pc in planned.orders],
        )

    return result


async def _enqueue_rider_assignment(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider_phone: str,
    batch_id: int,
    orders: list,
) -> None:
    """Notify the rider of a new batch.

    Rider assignment is business-INITIATED, so outside WhatsApp's 24h window a
    free-form interactive button is rejected. When ``wa_rider_assign_template``
    is configured we send an approved TEMPLATE (delivers anytime); the quick-reply
    button still carries ``picked:{batch_id}`` so the existing rider flow is
    unchanged. With no template configured we send a rich free-form summary
    (customer name, address, COD amount per order) so the rider knows the job
    up-front; the map/navigation link is intentionally withheld until pickup
    (flow integrity — see rider_flow).
    """
    from app.config import get_settings

    settings = get_settings()
    order_numbers = ", ".join(o.order_number for o in orders)
    tmpl = settings.wa_rider_assign_template
    if tmpl:
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=rider_phone,
            msg_type=OutboundMessageType.TEMPLATE,
            payload={
                "name": tmpl,
                "language": settings.wa_rider_assign_template_lang,
                "components": [
                    {
                        "type": "body",
                        "parameters": [{"type": "text", "text": order_numbers}],
                    },
                    {
                        "type": "button",
                        "sub_type": "quick_reply",
                        "index": "0",
                        "parameters": [
                            {"type": "payload", "payload": f"picked:{batch_id}"}
                        ],
                    },
                ],
            },
            idempotency_key=f"assign-{batch_id}",
        )
        return

    # Free-form rich summary (dev/test/mock + inside-24h window).
    from app.dispatch.rider_flow import _stop_details

    blocks: list[str] = []
    for o in orders:
        name, address_str, _coords = await _stop_details(session, o)
        lines = [f"*Order {o.order_number}*"]
        if name:
            lines.append(f"👤 {name}")
        if address_str:
            lines.append(f"📍 {address_str}")
        if o.total:
            lines.append(f"💵 Collect AED {o.total:.2f}")
        blocks.append("\n".join(lines))

    header = (
        "🛵 *New delivery assigned*"
        if len(orders) == 1
        else f"🛵 *New batch assigned* — {len(orders)} orders"
    )
    body = header + "\n\n" + "\n\n".join(blocks) + "\n\nTap below once you've picked up."

    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=rider_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={
            "body": body,
            "buttons": [{"id": f"picked:{batch_id}", "title": "Orders Picked"}],
        },
        idempotency_key=f"assign-{batch_id}",
    )


async def reassign_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    new_rider_id: int,
    actor: str = "manager",
) -> Order:
    """Manually move an ASSIGNED order to a manager-chosen rider.

    Recovery path for a stuck assignment (e.g. the original rider was never
    reachable so the delivery never advanced). Moves the order into a fresh
    single-order batch for the new rider, frees the old rider when they have no
    other live orders, records the decision for explainability, and notifies the
    new rider via the 24h-window-safe assignment helper.

    Only ASSIGNED orders are reassignable — after pickup the original rider
    physically holds the food, so reassigning would be incorrect. Caller commits.
    """
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        raise ValueError("Order not found")
    if str(order.status) != str(OrderStatus.ASSIGNED):
        raise ValueError(
            f"Only assigned orders can be reassigned (current: '{order.status}')."
        )
    new_rider = await session.get(Rider, new_rider_id)
    if new_rider is None or new_rider.restaurant_id != restaurant_id:
        raise ValueError("Rider not found")
    if new_rider.status == "deactivated":
        raise ValueError("Cannot reassign to a deactivated rider.")
    old_rider_id = order.rider_id
    if old_rider_id == new_rider_id:
        raise ValueError("Order is already assigned to this rider.")

    # Detach the order from its current batch; mark that batch completed if empty.
    bo = await session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == order.id)
    )
    old_batch_id = bo.batch_id if bo is not None else None
    if bo is not None:
        await session.delete(bo)
        await session.flush()

    # Fresh single-order batch for the new rider.
    batch = Batch(
        restaurant_id=restaurant_id, rider_id=new_rider_id,
        status="planned", route={},
    )
    session.add(batch)
    await session.flush()
    session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=1))
    order.rider_id = new_rider_id

    # Explainability + timeline.
    session.add(
        Assignment(
            order_id=order.id, rider_id=new_rider_id, batch_id=batch.id,
            assigned_at=datetime.now(timezone.utc),
            algorithm_score={
                "manual_reassign": True,
                "previous_rider_id": old_rider_id,
                "actor": actor,
            },
        )
    )
    await record_audit(
        session,
        actor=actor,
        restaurant_id=restaurant_id,
        entity="order",
        entity_id=str(order.id),
        action="reassigned",
        before={"rider_id": old_rider_id},
        after={"rider_id": new_rider_id, "previous_rider_id": old_rider_id},
    )

    new_rider.status = "on_delivery"

    # Free the old rider when they have no other live orders.
    if old_rider_id and old_rider_id != new_rider_id:
        old_rider = await session.get(Rider, old_rider_id)
        if old_rider is not None and old_rider.status != "deactivated":
            live = await session.scalar(
                select(func.count(Order.id)).where(
                    Order.rider_id == old_rider_id,
                    Order.status.in_(
                        [
                            OrderStatus.ASSIGNED,
                            OrderStatus.PICKED_UP,
                            OrderStatus.ARRIVING,
                        ]
                    ),
                )
            )
            if not live:
                old_rider.status = "available"

    if old_batch_id is not None:
        remaining = await session.scalar(
            select(func.count(BatchOrder.id)).where(
                BatchOrder.batch_id == old_batch_id
            )
        )
        if not remaining:
            old_batch = await session.get(Batch, old_batch_id)
            if old_batch is not None:
                old_batch.status = "completed"

    # Notify the new rider (template-aware → delivers even outside the 24h window).
    await _enqueue_rider_assignment(
        session,
        restaurant_id=restaurant_id,
        rider_phone=new_rider.phone,
        batch_id=batch.id,
        orders=[order],
    )
    return order
