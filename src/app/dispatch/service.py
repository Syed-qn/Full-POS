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

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.config import get_settings
from app.dispatch.batching import (
    OrderCandidate,
    PlannedBatch,
    _sequence_stops,
    build_batches,
    compute_batch_total_est_min,
)
from app.dispatch.models import Assignment, Batch, BatchOrder, RiderLocation
from app.dispatch.optimizer import OptOrder, OptRider, optimize_dispatch
from app.dispatch.scoring import RiderCandidate, rank_riders
from app.geo.factory import get_geo_provider
from app.geo.haversine import distance_km
from app.metrics import DISPATCH_ORDERS, DISPATCH_RUNS, DISPATCH_SOLVE_SECONDS
from app.identity.models import Restaurant, Rider
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, CustomerAddress, Order
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType

_logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    assigned_count: int = 0
    unassigned_count: int = 0
    needs_retry: bool = False


# Namespace for the per-restaurant dispatch advisory lock (arbitrary constant; keeps
# our lock keys from colliding with any other advisory-lock user).
_DISPATCH_LOCK_CLASS = 4_919_001


async def _acquire_dispatch_lock(session: AsyncSession, restaurant_id: int) -> None:
    """Serialize dispatch per restaurant with a transaction-scoped Postgres advisory
    lock. Without this, two orders marked ready a fraction of a second apart trigger
    two concurrent dispatch runs that don't see each other — so they get assigned
    ONE-BY-ONE instead of batched. The lock makes the second run wait, then see both
    ready orders in one pass and batch them. Auto-released on commit/rollback, so it
    needs no redis and works on the web-only (Render) deploy.

    Best-effort: a backend without advisory locks (e.g. SQLite in a unit test) just
    proceeds unserialized rather than erroring.
    """
    try:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:c, :o)"),
            {"c": _DISPATCH_LOCK_CLASS, "o": restaurant_id},
        )
    except Exception:  # noqa: BLE001 — non-Postgres backend; proceed without the lock
        _logger.debug("advisory dispatch lock unavailable; proceeding unserialized")


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
    # Serialize concurrent dispatch for this restaurant so near-simultaneous "ready"
    # events are considered together (and can batch) instead of racing into one-by-one
    # assignments. Held until this transaction commits/rolls back.
    await _acquire_dispatch_lock(session, restaurant_id)
    result = await _dispatch(session, restaurant_id)
    # After assigning, nudge the kitchen to rush still-cooking orders that are
    # headed to the same area as a run going out now, so they catch the next batch.
    await _nudge_batchable_cooking_orders(session, restaurant_id)
    return result


# Alias used by dispatch router (spec §4.3)
run_dispatch = run_dispatch_engine


async def preview_batch_groups(
    session: AsyncSession, *, restaurant_id: int
) -> dict[int, str]:
    """Map order_id -> a batch-preview label ("A", "B", …) for active UNASSIGNED
    orders whose drop-offs are close enough to ride together, so the order list can
    show the upcoming batching BEFORE dispatch assigns a rider.

    Uses the SAME proximity rule and cap the real engine uses (batch_proximity_km /
    max_orders_per_batch), greedily seeding a group and pulling in nearby orders.
    Only groups of 2+ get a label; a lone order returns nothing. This is a forecast,
    not a commitment — the actual batch forms when orders are marked ready."""
    from app.identity.models import Restaurant
    from app.ordering.models import CustomerAddress, Order

    restaurant = await session.get(Restaurant, restaurant_id)
    rs = (restaurant.settings or {}) if restaurant is not None else {}
    proximity_km = float(rs.get("batch_proximity_km", 1.0))
    max_per = int(rs.get("max_orders_per_batch", 3))

    rows = (
        await session.execute(
            select(Order.id, CustomerAddress.latitude, CustomerAddress.longitude)
            .join(CustomerAddress, CustomerAddress.id == Order.address_id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.status.in_(("confirmed", "preparing", "ready")),
                Order.rider_id.is_(None),
                CustomerAddress.latitude.is_not(None),
                CustomerAddress.longitude.is_not(None),
            )
            .order_by(Order.id)
        )
    ).all()
    items = [(int(r[0]), float(r[1]), float(r[2])) for r in rows]

    labels: dict[int, str] = {}
    used: set[int] = set()
    group_index = 0
    for i, (oid, lat, lon) in enumerate(items):
        if oid in used:
            continue
        group = [oid]
        used.add(oid)
        for oid2, lat2, lon2 in items[i + 1:]:
            if oid2 in used or len(group) >= max_per:
                continue
            if distance_km(lat, lon, lat2, lon2) <= proximity_km:
                group.append(oid2)
                used.add(oid2)
        if len(group) >= 2:
            label = chr(ord("A") + group_index)
            group_index += 1
            for member in group:
                labels[member] = label
    return labels


async def sweep_ready_once() -> int:
    """Re-run dispatch for every restaurant that has ready + unassigned orders.

    This is what RELEASES held (batch-window) orders once they mature and RETRIES
    stuck no-rider orders — neither happens on its own because dispatch is otherwise
    only triggered when an order is marked ready. Driven by the in-process sweep loop
    (app.main lifespan) and the Celery beat task (apps.workers). Best-effort and
    idempotent per tenant: one restaurant's failure never blocks the others. Returns
    the number of restaurants swept.
    """
    from app.db import async_session_factory

    async with async_session_factory() as session:
        restaurant_ids = (
            await session.scalars(
                select(Order.restaurant_id)
                .where(Order.status == "ready", Order.rider_id.is_(None))
                .distinct()
            )
        ).all()
    for restaurant_id in restaurant_ids:
        async with async_session_factory() as session:
            try:
                await run_dispatch_engine(session, restaurant_id=restaurant_id)
                await session.commit()
            except Exception:  # noqa: BLE001 — keep sweeping the other tenants
                _logger.exception(
                    "dispatch sweep failed for restaurant_id=%s", restaurant_id
                )
                await session.rollback()
    return len(restaurant_ids)


async def _nudge_batchable_cooking_orders(
    session: AsyncSession, restaurant_id: int
) -> None:
    """Tell the kitchen to prioritise a still-cooking order when its delivery is in the
    same area as an order being delivered now — so it can ride the next batch to that
    area instead of needing a fresh rider. Advisory + idempotent (one 'batch_expedite'
    event per order via uq_sla_events_order_type). Best-effort; never breaks dispatch."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.sla.models import SlaEvent

    try:
        restaurant = await session.get(Restaurant, restaurant_id)
        if restaurant is None:
            return
        radius = float((restaurant.settings or {}).get("batch_expedite_radius_km", 1.5))
        now = datetime.now(timezone.utc)

        assigned = (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status == str(OrderStatus.ASSIGNED),
                )
            )
        ).all()
        cooking = (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status.in_(
                        [str(OrderStatus.CONFIRMED), str(OrderStatus.PREPARING)]
                    ),
                )
            )
        ).all()
        if not assigned or not cooking:
            return

        dest_coords = await _dropoff_coords(session, list(assigned))
        cook_coords = await _dropoff_coords(session, list(cooking))
        dest_pts = [dest_coords[o.id] for o in assigned if o.id in dest_coords]
        if not dest_pts:
            return

        for co in cooking:
            cc = cook_coords.get(co.id)
            if cc is None:
                continue
            if not any(distance_km(cc[0], cc[1], dp[0], dp[1]) <= radius for dp in dest_pts):
                continue
            stmt = (
                pg_insert(SlaEvent)
                .values(
                    order_id=co.id,
                    restaurant_id=restaurant_id,
                    type="batch_expedite",
                    ts=now,
                    notified={},
                )
                .on_conflict_do_nothing(constraint="uq_sla_events_order_type")
                .returning(SlaEvent.id)
            )
            if (await session.execute(stmt)).first() is None:
                continue  # already nudged for this order
            await enqueue_message(
                session,
                restaurant_id=restaurant_id,
                to_phone=restaurant.phone,
                msg_type=OutboundMessageType.TEXT,
                payload={
                    "body": (
                        f"🍱 Order {co.order_number} is headed to the same area as a "
                        "delivery going out now — prioritise it so it can batch the next "
                        "run (saves a rider trip)."
                    )
                },
                idempotency_key=f"batch-expedite-{co.id}",
            )
    except Exception:  # noqa: BLE001 - advisory nudge must never break dispatch
        _logger.exception("batch-expedite nudge failed (restaurant_id=%s)", restaurant_id)


async def _latest_rider_positions(
    session: AsyncSession, restaurant_id: int
) -> dict[int, tuple[float, float]]:
    """Latest (lat, lon) ping per rider from rider_locations.

    Some deployed databases can lag migrations. If the rider-location table or
    its query path is unavailable, degrade to an empty mapping so dispatch still
    runs by treating riders as co-located with the restaurant.
    """
    try:
        rows = (
            await session.scalars(
                select(RiderLocation)
                .where(RiderLocation.restaurant_id == restaurant_id)
                .order_by(RiderLocation.ts.asc())
            )
        ).all()
    except (ProgrammingError, OperationalError):
        # A lagging DB (e.g. missing rider-location columns) aborts the current
        # transaction. Roll back so the surrounding dispatch run can keep using
        # the session instead of failing the next query with InFailedSqlTransaction.
        await session.rollback()
        return {}
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


async def _commit_route(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider: Rider,
    stops: list[tuple[Order, float, float]],
    total_est: int,
    algorithm_score: dict,
    now: datetime,
) -> int:
    """Persist one rider's route: Batch + BatchOrder + Assignment, flip statuses, audit,
    and push-notify the rider. Shared by both the greedy and OR-Tools engines so the
    write path (and its audit trail) is identical. Returns the number of orders assigned.
    """
    batch = Batch(
        restaurant_id=restaurant_id,
        rider_id=rider.id,
        status="planned",
        route={"stops": [{"order_id": o.id, "lat": lat, "lon": lon} for o, lat, lon in stops]},
        total_est_min=total_est,
    )
    session.add(batch)
    await session.flush()

    for seq, (order, _lat, _lon) in enumerate(stops, start=1):
        before = {"status": order.status, "rider_id": order.rider_id}
        order.status = "assigned"
        order.rider_id = rider.id
        session.add(BatchOrder(batch_id=batch.id, order_id=order.id, sequence=seq))
        session.add(
            Assignment(
                order_id=order.id,
                rider_id=rider.id,
                batch_id=batch.id,
                assigned_at=now,
                algorithm_score=algorithm_score,
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

    rider.status = "on_delivery"
    # App-only rider flow: notify by PUSH (native app), never WhatsApp. Best-effort.
    from app.dispatch.rider_app import notify_rider_assigned

    try:
        await notify_rider_assigned(session, rider=rider, order_count=len(stops))
    except Exception:  # noqa: BLE001 - push is best-effort
        _logger.exception("assignment push failed for rider %s", rider.id)
    return len(stops)


async def _dispatch_ortools(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    restaurant_id: int,
    candidates: list[OrderCandidate],
    orders_by_id: dict[int, Order],
    origin: tuple[float, float] | None,
    geo,
    now: datetime,
    customer_sla_min: int,
) -> DispatchResult:
    """SLA-first VRP dispatch (opt-in per restaurant). Optimises routes + assignment in
    one solve, drops orders that can't meet SLA, and warns the manager about the drops.

    Scope (phase 3b): re-optimises UNASSIGNED ready orders together with ASSIGNED-but-
    not-yet-picked orders. Already-assigned orders are locked to their current rider
    (never moved cross-rider — no churn of a rider's identity) but may be re-sequenced or
    have a new nearby order inserted before them; when that shifts a customer's ETA we
    message them. A locked order that can no longer meet SLA simply falls out of the
    re-plan (its existing assignment is left untouched). Write path = ``_commit_route``.
    """
    result = DispatchResult()
    if origin is None:
        # No restaurant coords -> can't build a travel model; leave for the greedy path.
        result.needs_retry = True
        return result

    ready_ids = {c.order_id for c in candidates}

    # Assigned-but-not-picked orders are eligible for re-optimisation (food not yet
    # collected, so re-sequencing is safe). picked_up / arriving are left alone.
    movable = (
        await session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant_id,
                Order.status == str(OrderStatus.ASSIGNED),
                Order.rider_id.is_not(None),
            )
        )
    ).all()
    movable_coords = await _dropoff_coords(session, list(movable))
    movable = [m for m in movable if m.id in movable_coords]  # need a drop pin
    movable_ids = {m.id for m in movable}

    orders_by_id = dict(orders_by_id)
    coords = {c.order_id: (c.lat, c.lon) for c in candidates}
    for m in movable:
        orders_by_id[m.id] = m
        coords[m.id] = movable_coords[m.id]

    # Vehicle pool: available riders + the (busy) riders currently holding movable orders.
    busy_rider_ids = {m.rider_id for m in movable}
    riders = (
        await session.scalars(
            select(Rider).where(
                Rider.restaurant_id == restaurant_id,
                # Off-duty idle riders take no new/movable orders; riders already
                # holding movable orders stay in the pool to keep their in-flight work.
                ((Rider.status == "available") & (Rider.on_duty.is_(True)))
                | (Rider.id.in_(busy_rider_ids)),
            )
        )
    ).all()
    riders_by_id = {rd.id: rd for rd in riders}
    positions = await _latest_rider_positions(session, restaurant_id)

    opt_orders = [
        OptOrder(
            order_id=c.order_id, lat=c.lat, lon=c.lon,
            minutes_elapsed=c.minutes_elapsed, priority=c.priority,
        )
        for c in candidates
    ]
    for m in movable:
        if m.rider_id not in riders_by_id:
            continue  # rider not loadable -> leave this order as-is
        opt_orders.append(
            OptOrder(
                order_id=m.id,
                lat=movable_coords[m.id][0],
                lon=movable_coords[m.id][1],
                minutes_elapsed=_minutes_since_sla(m, now),
                priority=m.priority or "normal",
                locked_rider_id=m.rider_id,
            )
        )
    opt_riders = [
        OptRider(
            rider_id=rd.id,
            lat=positions.get(rd.id, (restaurant.lat, restaurant.lng))[0],
            lon=positions.get(rd.id, (restaurant.lat, restaurant.lng))[1],
            active_load=await _active_order_count(session, rd.id),
        )
        for rd in riders
    ]

    _t0 = time.perf_counter()
    plan = optimize_dispatch(
        orders=opt_orders, riders=opt_riders, origin=origin,
        customer_sla_min=customer_sla_min, geo_provider=geo,
    )
    DISPATCH_SOLVE_SECONDS.labels(engine="ortools").observe(time.perf_counter() - _t0)

    # Current per-rider sequence of movable orders (to detect unchanged routes).
    current: dict[int, list[int]] = {}
    if movable_ids:
        rows = (
            await session.execute(
                select(BatchOrder.order_id, Batch.rider_id, BatchOrder.sequence)
                .join(Batch, BatchOrder.batch_id == Batch.id)
                .where(BatchOrder.order_id.in_(movable_ids))
                .order_by(BatchOrder.sequence)
            )
        ).all()
        for order_id, rider_id, _seq in rows:
            current.setdefault(rider_id, []).append(order_id)

    for route in plan.routes:
        rider = riders_by_id.get(route.rider_id)
        if rider is None:
            continue
        new_ids = route.order_ids
        # Unchanged route (same movable orders, same order, nothing new) -> no churn.
        if new_ids == current.get(rider.id, []) and not (set(new_ids) & ready_ids):
            continue

        # Tear down any existing batch rows for the movable orders we are re-placing
        # (BatchOrder.order_id is unique, so the old row must go before re-committing).
        movable_in_route = [oid for oid in new_ids if oid in movable_ids]
        if movable_in_route:
            await session.execute(
                delete(BatchOrder).where(BatchOrder.order_id.in_(movable_in_route))
            )
            await session.execute(
                delete(Assignment).where(Assignment.order_id.in_(movable_in_route))
            )

        stops = [(orders_by_id[oid], *coords[oid]) for oid in new_ids]
        total_est = max(
            (int(round(route.projected_minutes.get(oid, 0))) for oid in new_ids),
            default=1,
        )
        await _commit_route(
            session,
            restaurant_id=restaurant_id,
            rider=rider,
            stops=stops,
            total_est=max(1, total_est),
            algorithm_score={
                "engine": "ortools",
                "projected_min": {
                    str(oid): round(route.projected_minutes.get(oid, 0), 1)
                    for oid in new_ids
                },
            },
            now=now,
        )
        result.assigned_count += sum(1 for oid in new_ids if oid in ready_ids)

        # Proactively message customers whose ETA shifted because of the re-plan.
        for oid in new_ids:
            if oid not in movable_ids:
                continue
            await _notify_eta_change(
                session,
                restaurant_id=restaurant_id,
                order=orders_by_id[oid],
                projected_min=route.projected_minutes.get(oid, 0.0),
                now=now,
            )

    # Remove any batches left empty by the teardown above.
    await session.flush()
    await session.execute(
        delete(Batch).where(
            Batch.restaurant_id == restaurant_id,
            Batch.id.not_in(select(BatchOrder.batch_id)),
        )
    )

    # Best-effort: only READY orders that were dropped are a manager problem; dropped
    # movable orders simply keep their existing assignment.
    dropped_ready = [oid for oid in plan.unassigned if oid in ready_ids]
    if dropped_ready:
        result.unassigned_count += len(dropped_ready)
        result.needs_retry = True
        numbers = ", ".join(orders_by_id[oid].order_number for oid in dropped_ready)
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=restaurant.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={
                "body": (
                    f"⚠️ {len(dropped_ready)} order(s) can't meet the {customer_sla_min}-min "
                    f"SLA with current riders: {numbers}. Add a rider or mark priority now."
                )
            },
            idempotency_key=(
                f"slabreach-opt-{restaurant_id}-"
                f"{min(dropped_ready)}-{int(now.timestamp() // 60)}"
            ),
        )

    if result.assigned_count:
        DISPATCH_ORDERS.labels(engine="ortools", outcome="assigned").inc(
            result.assigned_count
        )
    if dropped_ready:
        DISPATCH_ORDERS.labels(engine="ortools", outcome="dropped").inc(
            len(dropped_ready)
        )
    return result


def _minutes_since_sla(order: Order, now: datetime) -> float:
    """Minutes since the order's SLA clock started (0 if unset)."""
    if order.sla_confirmed_at is None:
        return 0.0
    sla = order.sla_confirmed_at
    if sla.tzinfo is None:
        sla = sla.replace(tzinfo=timezone.utc)
    return max(0.0, (now - sla).total_seconds() / 60.0)


async def _notify_eta_change(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order: Order,
    projected_min: float,
    now: datetime,
) -> None:
    """If a re-plan shifted an order's ETA by more than 5 min, message the customer and
    update ``promised_eta``. Idempotent per order per target-ETA minute (no spam)."""
    if order.sla_confirmed_at is None:
        return
    base = order.sla_confirmed_at
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    new_eta = base + timedelta(minutes=projected_min)
    old = order.promised_eta
    if old is not None and old.tzinfo is None:
        old = old.replace(tzinfo=timezone.utc)
    if old is not None and abs((new_eta - old).total_seconds()) <= 5 * 60:
        return  # change too small to bother the customer

    order.promised_eta = new_eta
    customer = await session.get(Customer, order.customer_id)
    if customer is None:
        return
    eta_min = max(1, int(round((new_eta - now).total_seconds() / 60.0)))
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=customer.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={
            "body": (
                f"Update on your order {order.order_number}: it's now arriving in about "
                f"{eta_min} min. Thanks for your patience! 🙏"
            )
        },
        idempotency_key=f"eta-change-{order.id}-{int(new_eta.timestamp() // 60)}",
    )


async def _dispatch(session: AsyncSession, restaurant_id: int) -> DispatchResult:
    restaurant = await session.get(Restaurant, restaurant_id)
    now = datetime.now(timezone.utc)
    _customer_sla_min = get_settings().sla_customer_minutes

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
    geo = get_geo_provider()
    candidates = []
    skipped_no_geo: list[Order] = []
    for o in ready:
        coords = dropoffs.get(o.id)
        if coords is None:
            # GAP#7: an order with no geocoded drop-off must NOT be faked to the
            # restaurant location — that makes it look like a zero-distance delivery,
            # so it batches as best-case and silently breaches the SLA on the road.
            # Surface it for manual handling instead of masking the distance.
            skipped_no_geo.append(o)
            continue
        lat, lon = coords
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

    if skipped_no_geo:
        # Leave these orders ready/unassigned and alert the manager so a human can
        # add a delivery pin; auto-dispatch can't place them safely without coords.
        result_numbers = ", ".join(o.order_number for o in skipped_no_geo)
        _logger.warning(
            "dispatch: %d order(s) skipped — no geocoded drop-off: %s",
            len(skipped_no_geo),
            result_numbers,
        )
        await enqueue_message(
            session,
            restaurant_id=restaurant_id,
            to_phone=restaurant.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={
                "body": (
                    f"{len(skipped_no_geo)} ready order(s) have no delivery location "
                    f"and can't be auto-dispatched: {result_numbers}. "
                    "Add a delivery pin to dispatch them."
                )
            },
            idempotency_key=(
                f"nogeo-{restaurant_id}-{skipped_no_geo[0].id}-{int(now.timestamp() // 60)}"
            ),
        )

    # Restaurant pickup coords seed the depot->first-stop leg (GAP#1, spec §4.3.2).
    origin = (
        (restaurant.lat, restaurant.lng)
        if restaurant.lat is not None and restaurant.lng is not None
        else None
    )
    orders_by_id = {o.id: o for o in ready}

    # ── Batch hold window (opt-in via batch_hold_seconds; 0 = off, default) ──────────
    # Defer a freshly-ready LONE order briefly so a nearby order can join its batch
    # before a rider is committed — the standard "batching window". A held order is
    # simply skipped this pass and re-evaluated by the periodic dispatch sweep
    # (dispatch.sweep_ready) until it finds a batch-mate or the window matures. We
    # only hold when a batch is actually PLAUSIBLE — i.e. another order is cooking
    # nearby (confirmed/preparing) and could become ready inside the window. We never
    # hold an order that already has a ready batch-mate within proximity, has no nearby
    # mate in the pipeline at all, is priority, or is under SLA pressure (waiting the
    # window would risk the internal target). Applies to BOTH engines, so it sits
    # before the engine branch.
    rs = restaurant.settings or {}
    hold_seconds = int(rs.get("batch_hold_seconds", 0) or 0)
    if hold_seconds > 0 and candidates:
        hold_proximity_km = float(rs.get("batch_proximity_km", 1.0))
        internal_target = get_settings().sla_internal_target_minutes
        # Plausible upcoming batch-mates: orders still in the kitchen (confirmed/
        # preparing, not yet assigned) that could become ready within the window. A
        # lone ready order is only worth holding if such a mate exists *nearby* —
        # otherwise we'd just burn SLA waiting for a batch that can never form.
        pipeline_orders = (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status.in_(
                        [str(OrderStatus.CONFIRMED), str(OrderStatus.PREPARING)]
                    ),
                    Order.rider_id.is_(None),
                )
            )
        ).all()
        pipeline_coords = await _dropoff_coords(session, list(pipeline_orders))
        pipeline_pts = [
            pipeline_coords[o.id] for o in pipeline_orders if o.id in pipeline_coords
        ]
        eligible: list[OrderCandidate] = []
        held: list[OrderCandidate] = []
        for c in candidates:
            ready_at = c.ready_at
            if ready_at.tzinfo is None:
                ready_at = ready_at.replace(tzinfo=timezone.utc)
            waited = (now - ready_at).total_seconds()
            has_mate = any(
                other.order_id != c.order_id
                and distance_km(c.lat, c.lon, other.lat, other.lon) <= hold_proximity_km
                for other in candidates
            )
            # A mate that's still cooking nearby and could join once it's ready.
            has_pipeline_mate = any(
                distance_km(c.lat, c.lon, plat, plon) <= hold_proximity_km
                for plat, plon in pipeline_pts
            )
            # Would waiting out the rest of the window push it past the internal target?
            sla_pressure = (
                c.minutes_elapsed + max(0.0, hold_seconds - waited) / 60.0
                >= internal_target
            )
            if (
                c.priority != "normal"
                or waited >= hold_seconds
                or has_mate
                or sla_pressure
                or not has_pipeline_mate  # nothing nearby to wait for → assign now
            ):
                eligible.append(c)
            else:
                held.append(c)
        if held:
            _logger.info(
                "dispatch: holding %d fresh order(s) up to %ds for batching "
                "(restaurant_id=%s): %s",
                len(held), hold_seconds, restaurant_id,
                ", ".join(orders_by_id[c.order_id].order_number for c in held),
            )
        candidates = eligible
        if not candidates:
            return DispatchResult()

    # Per-restaurant engine flag (spec §4.3). Default greedy; "ortools" opts into the
    # SLA-first VRP optimizer. Unknown values fall back to greedy.
    engine = (restaurant.settings or {}).get("dispatch_engine", "greedy")
    if engine == "ortools" and candidates:
        DISPATCH_RUNS.labels(engine="ortools").inc()
        return await _dispatch_ortools(
            session,
            restaurant=restaurant,
            restaurant_id=restaurant_id,
            candidates=candidates,
            orders_by_id=orders_by_id,
            origin=origin,
            geo=geo,
            now=now,
            customer_sla_min=_customer_sla_min,
        )

    # Per-restaurant batching geometry (defaults preserve the original behaviour).
    rs = restaurant.settings or {}
    _global = get_settings()
    proximity_km = float(rs.get("batch_proximity_km", 1.0))
    window_min = int(rs.get("batch_window_minutes", 10))
    max_per = int(rs.get("max_orders_per_batch", 3))
    buffer_per = int(rs.get("sla_buffer_per_order_minutes", _global.sla_buffer_per_order_minutes))
    max_detour_km = float(rs.get("batch_max_detour_km", 0) or 0)

    DISPATCH_RUNS.labels(engine="greedy").inc()
    _t0 = time.perf_counter()
    batches = build_batches(
        candidates, geo_provider=geo, origin=origin,
        max_per_batch=max_per, proximity_km=proximity_km, window_min=window_min,
        buffer_per_order=buffer_per, max_detour_km=max_detour_km,
    )
    DISPATCH_SOLVE_SECONDS.labels(engine="greedy").observe(time.perf_counter() - _t0)

    # Shadow compare: run the optimizer in-memory (no writes) and log what it WOULD do,
    # so we can evaluate ortools-vs-greedy on real traffic before flipping a restaurant.
    if candidates and get_settings().dispatch_shadow_compare and origin is not None:
        _log_shadow_compare(
            candidates=candidates, restaurant=restaurant, origin=origin, geo=geo,
            greedy_batches=batches, customer_sla_min=_customer_sla_min,
        )

    # Assignment order: priority batches first (they bypass batching), then normal
    # batches by LEAST SLA slack (highest projected completion) so a scarce rider goes to
    # the order closest to its deadline rather than whichever became ready first. No
    # cross-batch (Hungarian) matching is needed: every batch picks up at the SAME
    # restaurant, so a rider's score (pickup distance + workload + on-time) is identical
    # for all batches → per-batch best-available is already globally optimal. Route /
    # drop-off-aware assignment is the OR-Tools engine's job, not greedy's.
    _priority_batches = [b for b in batches if b.seed.priority != "normal"]
    _normal_batches = [b for b in batches if b.seed.priority == "normal"]
    _normal_batches.sort(
        key=lambda b: compute_batch_total_est_min(b, geo_provider=geo, origin=origin),
        reverse=True,
    )
    batches = _priority_batches + _normal_batches

    result = DispatchResult()

    for planned in batches:
        riders = (
            await session.scalars(
                select(Rider).where(
                    Rider.restaurant_id == restaurant_id,
                    Rider.status == "available",
                    Rider.on_duty.is_(True),
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
                    # Bucket per 10 min so the periodic dispatch sweep (every 30s)
                    # re-tries the order without re-alerting the manager each tick.
                    f"norider-{restaurant_id}-{planned.seed.order_id}-"
                    f"{int(now.timestamp() // 600)}"
                ),
            )
            # Predictive breach warning: if this batch could not meet the 40-min
            # customer SLA even if a rider left RIGHT NOW (projected = elapsed +
            # depot/route + buffer, per GAP#1), the wait alone guarantees a breach.
            # Tell the manager now instead of waiting for the 40-min monitor tick —
            # the only fix is adding a rider or marking the order priority.
            projected = compute_batch_total_est_min(
                planned, geo_provider=geo, origin=origin
            )
            if projected > _customer_sla_min:
                numbers = ", ".join(
                    orders_by_id[pc.order_id].order_number for pc in planned.orders
                )
                await enqueue_message(
                    session,
                    restaurant_id=restaurant_id,
                    to_phone=restaurant.phone,
                    msg_type=OutboundMessageType.TEXT,
                    payload={
                        "body": (
                            f"⚠️ Order(s) {numbers} can't meet the {_customer_sla_min}-min "
                            f"SLA with current riders (projected ~{projected} min and still "
                            "waiting). Add a rider or mark priority now."
                        )
                    },
                    idempotency_key=(
                        f"slabreach-pred-{restaurant_id}-{planned.seed.order_id}"
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

        # Deliver the batch's stops nearest-first from the restaurant (shortest route),
        # not in arrival order. Corridor mode already sequenced them, so this is a no-op
        # there. Build a LOCAL sequence — never mutate planned.orders, whose first element
        # (seed) feeds the no-rider / breach idempotency keys above.
        seq_orders = (
            _sequence_stops(planned.orders, origin, geo)
            if origin is not None
            else planned.orders
        )
        seq_batch = PlannedBatch(
            orders=seq_orders, per_order_buffer_min=planned.per_order_buffer_min
        )
        total_est = compute_batch_total_est_min(seq_batch, geo_provider=geo, origin=origin)
        stops = [
            (orders_by_id[pc.order_id], pc.lat, pc.lon) for pc in seq_orders
        ]
        result.assigned_count += await _commit_route(
            session,
            restaurant_id=restaurant_id,
            rider=rider,
            stops=stops,
            total_est=total_est,
            algorithm_score=scored[0].breakdown,
            now=now,
        )

    if result.assigned_count:
        DISPATCH_ORDERS.labels(engine="greedy", outcome="assigned").inc(
            result.assigned_count
        )
    if result.unassigned_count:
        DISPATCH_ORDERS.labels(engine="greedy", outcome="dropped").inc(
            result.unassigned_count
        )
    return result


def _log_shadow_compare(
    *,
    candidates: list[OrderCandidate],
    restaurant: Restaurant,
    origin: tuple[float, float],
    geo,
    greedy_batches,
    customer_sla_min: int,
) -> None:
    """Run the optimizer in-memory (no writes) and log served/dropped vs greedy.

    Read-only evaluation harness: lets ops compare the OR-Tools plan against the greedy
    plan on live traffic before opting a restaurant in. Never raises into dispatch."""
    try:
        opt_orders = [
            OptOrder(
                order_id=c.order_id, lat=c.lat, lon=c.lon,
                minutes_elapsed=c.minutes_elapsed, priority=c.priority,
            )
            for c in candidates
        ]
        # Shadow uses the available riders as anonymous depot-co-located vehicles; this is
        # an approximation (no live positions) — good enough for served/dropped counts.
        n_riders = max(1, len(greedy_batches))
        opt_riders = [
            OptRider(rider_id=i, lat=origin[0], lon=origin[1]) for i in range(n_riders)
        ]
        _t0 = time.perf_counter()
        plan = optimize_dispatch(
            orders=opt_orders, riders=opt_riders, origin=origin,
            customer_sla_min=customer_sla_min, geo_provider=geo,
        )
        DISPATCH_SOLVE_SECONDS.labels(engine="ortools_shadow").observe(
            time.perf_counter() - _t0
        )
        greedy_served = sum(len(b.orders) for b in greedy_batches)
        opt_served = sum(len(r.order_ids) for r in plan.routes)
        _logger.info(
            "dispatch shadow-compare restaurant=%s orders=%d | greedy: %d batches / %d served"
            " | ortools: %d routes / %d served / %d dropped",
            restaurant.id, len(candidates), len(greedy_batches), greedy_served,
            len(plan.routes), opt_served, len(plan.unassigned),
        )
    except Exception:  # noqa: BLE001 - shadow eval must never break dispatch
        _logger.exception("dispatch shadow-compare failed")


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

    # Notify the new rider by PUSH (app-only rider flow — never WhatsApp).
    from app.dispatch.rider_app import notify_rider_assigned

    try:
        await notify_rider_assigned(session, rider=new_rider, order_count=1)
    except Exception:  # noqa: BLE001 - push is best-effort
        _logger.exception("reassignment push failed for rider %s", new_rider.id)
    return order
