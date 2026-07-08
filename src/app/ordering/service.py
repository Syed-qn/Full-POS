from __future__ import annotations

import hashlib
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy import update as sa_update

from app.audit.service import record_audit
from app.config import get_settings
from app.geo.factory import get_geo_provider
from app.identity.models import Restaurant
from app.menu.models import Dish
from app.ordering.fsm import IllegalTransitionError, OrderStatus
from app.ordering.fsm import transition as fsm_transition
from app.ordering.habits import (
    OrderTimePrediction,
    build_usual_order_times,
    order_stamps_from_rows,
    predict_from_stamps,
)
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem

_logger = logging.getLogger(__name__)


async def compute_prep_deadline(
    session: "AsyncSession", order: Order, now: datetime
) -> datetime | None:
    """Kitchen "plate by" time: the latest the order can be ready and still leave enough
    of the customer SLA to drive it to the address. Distance-driven, not hardcoded:

        prep_deadline = sla_confirmed_at + customer_SLA − drive(restaurant→address)
                        − prep_handling − batch_safety

    ``now`` is the SLA-clock start (sla_confirmed_at). Returns None when the order has no
    geocoded drop-off (no drive leg to reason about). Never earlier than ``now`` — a
    delivery too far to make the SLA even with instant cooking yields "plate now", and
    the SLA monitor / predictive-breach path takes it from there. Handling + batch-safety
    minutes come from the restaurant's settings (per-tenant tunable)."""
    if order.address_id is None:
        return None
    addr = await session.get(CustomerAddress, order.address_id)
    if addr is None or addr.latitude is None or addr.longitude is None:
        return None
    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is None or restaurant.lat is None or restaurant.lng is None:
        return None

    geo = get_geo_provider()
    dist_km = geo.distance_km(restaurant.lat, restaurant.lng, addr.latitude, addr.longitude)
    drive_min = geo.eta_minutes(dist_km, buffer_minutes=0)

    rs = restaurant.settings or {}
    handling = int(rs.get("prep_handling_minutes", 5))
    safety = int(rs.get("batch_safety_minutes", 5))
    budget = get_settings().sla_customer_minutes - drive_min - handling - safety
    deadline = now + timedelta(minutes=budget)
    return max(deadline, now)


async def compute_cook_estimate(session: "AsyncSession", order: Order) -> int | None:
    """Estimated minutes to cook the order. Kitchens cook in parallel, so the slowest
    single dish gates readiness → max prep_minutes across the order's lines, falling back
    to the restaurant's default_prep_minutes for any dish without a set time. Returns None
    for an order with no items."""
    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    if not items:
        return None
    restaurant = await session.get(Restaurant, order.restaurant_id)
    default = int((restaurant.settings or {}).get("default_prep_minutes", 15)) if restaurant else 15
    dishes = (
        await session.scalars(
            select(Dish).where(Dish.id.in_({i.dish_id for i in items}))
        )
    ).all()
    prep_by = {d.id: d.prep_minutes for d in dishes}
    return max((prep_by.get(i.dish_id) or default) for i in items)


def _norm_pin(v: float | None) -> str:
    # ~11 m precision: same physical drop-off rounds to the same key.
    return f"{round(float(v), 4)}" if v is not None else ""


def _compute_exclusion_hash(
    phone: str,
    room_apartment: str | None = None,
    building: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> str:
    """Exclusion key = phone + door/apartment + building + pinned location, combined as a
    SINGLE hash → an AND gate: a buyer is barred ONLY when ALL of phone, room/apartment,
    building, AND pin match the canceller's. Any one differing → different hash → allowed.
    (Used by the offer matcher and the accept-time delivery guard.)"""
    room = (room_apartment or "").strip().lower()
    bld = (building or "").strip().lower()
    key = f"{phone}|{room}|{bld}|{_norm_pin(lat)}|{_norm_pin(lon)}"
    return hashlib.sha256(key.encode()).hexdigest()


def is_excluded_for_resale(
    exclusion_hash: str | None,
    *,
    phone: str,
    room_apartment: str | None = None,
    building: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> bool:
    """True only when the buyer's phone AND door/apartment AND building AND pinned
    location ALL match the canceller's (AND gate). Used to refuse re-delivering the
    cancelled food to the SAME address+phone, while allowing every genuinely different
    customer/address."""
    if not exclusion_hash:
        return False
    return _compute_exclusion_hash(phone, room_apartment, building, lat, lon) == exclusion_hash

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.menu.models import Dish
    from app.ordering.detail_schemas import OrderDetailOut


async def get_available_resale_orders(
    session: "AsyncSession",
    restaurant_id: int,
    phone: str,
    room_apartment: str | None = None,
    building: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> list[Order]:
    """Resale-offer matcher: on_resale orders this buyer is NOT excluded from. Exclusion is
    the AND of phone + door/apartment + building + pin (see is_excluded_for_resale). At
    offer time the buyer's address is usually unknown, so the full AND can't match → they
    see the offer; the strict same-address guard is re-checked at accept (delivery)."""
    # Only the resale *copy* rows are sellable (they carry exclusion_hash + items).
    # The cancelled original also transitions to on_resale but must not be offered.
    resales = (
        await session.scalars(
            select(Order).where(
                Order.restaurant_id == restaurant_id,
                Order.status == OrderStatus.ON_RESALE,
                Order.resale_of_order_id.isnot(None),
            )
        )
    ).all()
    available: list[Order] = []
    for r in resales:
        if not is_excluded_for_resale(
            r.exclusion_hash, phone=phone, room_apartment=room_apartment,
            building=building, lat=lat, lon=lon,
        ):
            available.append(r)
    return available


async def get_order_for_tenant(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    order_id: int,
) -> Order | None:
    """Fetch a single order scoped to the tenant. Returns None if not found."""
    return await session.scalar(
        select(Order).where(
            Order.id == order_id,
            Order.restaurant_id == restaurant_id,
        )
    )


def _dubai_day_start(ymd: str) -> datetime:
    """Start of a Dubai calendar day as naive UTC (matches DB ``created_at`` storage)."""
    from datetime import date, datetime, time, timezone
    from zoneinfo import ZoneInfo

    d = date.fromisoformat(ymd)
    aware = datetime.combine(d, time.min, tzinfo=ZoneInfo("Asia/Dubai"))
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


def _dubai_day_end_exclusive(ymd: str) -> datetime:
    """Start of the next Dubai calendar day as naive UTC (exclusive upper bound)."""
    from datetime import date, datetime, time, timedelta, timezone
    from zoneinfo import ZoneInfo

    d = date.fromisoformat(ymd) + timedelta(days=1)
    aware = datetime.combine(d, time.min, tzinfo=ZoneInfo("Asia/Dubai"))
    return aware.astimezone(timezone.utc).replace(tzinfo=None)


async def list_orders_for_tenant(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
    from_date: str | None = None,
    to_date: str | None = None,
    q: str | None = None,
    updated_since: datetime | None = None,
    scheduled_only: bool = False,
) -> list[Order]:
    """List orders for the tenant, newest first, with optional server-side filters.

    ``limit`` is clamped to [1, 100]. ``offset`` is clamped to >= 0.
    Date bounds use Asia/Dubai calendar days on ``created_at``.
    ``updated_since`` (used by the desktop pull-sync client) restricts results to rows
    with ``updated_at`` strictly after the given timestamp.
    """
    from sqlalchemy import or_

    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    stmt = select(Order).where(Order.restaurant_id == restaurant_id)
    if status:
        stmt = stmt.where(Order.status == status)
    if scheduled_only:
        stmt = stmt.where(Order.scheduled_for.is_not(None))
    if from_date:
        stmt = stmt.where(Order.created_at >= _dubai_day_start(from_date))
    if to_date:
        stmt = stmt.where(Order.created_at < _dubai_day_end_exclusive(to_date))
    if updated_since is not None:
        # updated_at is stored naive UTC; strip tzinfo from an offset-aware caller value
        # so asyncpg doesn't choke on a naive/aware comparison mismatch.
        if updated_since.tzinfo is not None:
            updated_since = updated_since.astimezone(timezone.utc).replace(tzinfo=None)
        stmt = stmt.where(Order.updated_at > updated_since)
    if q:
        term = q.strip().lstrip("#")
        if term:
            stmt = stmt.join(Customer, Customer.id == Order.customer_id)
            clauses = [
                Order.order_number.ilike(f"%{term}%"),
                Customer.name.ilike(f"%{term}%"),
                Customer.phone.ilike(f"%{term}%"),
            ]
            if term.isdigit():
                clauses.append(Order.id == int(term))
            stmt = stmt.where(or_(*clauses))
    stmt = stmt.order_by(Order.created_at.desc()).offset(offset).limit(limit)
    return list((await session.scalars(stmt)).all())


async def get_or_create_customer(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    phone: str,
) -> Customer:
    existing = await session.scalar(
        select(Customer).where(
            Customer.restaurant_id == restaurant_id,
            Customer.phone == phone,
        )
    )
    if existing:
        return existing
    customer = Customer(
        restaurant_id=restaurant_id,
        phone=phone,
        usual_order_times={},
        tags={},
        total_orders=0,
        total_spend=Decimal("0.00"),
    )
    session.add(customer)
    await session.flush()
    return customer


async def get_last_address(
    session: "AsyncSession",
    customer_id: int,
) -> CustomerAddress | None:
    return await session.scalar(
        select(CustomerAddress)
        .where(
            CustomerAddress.customer_id == customer_id,
            CustomerAddress.confirmed == True,  # noqa: E712
        )
        .order_by(CustomerAddress.last_used_at.desc().nullslast())
        .limit(1)
    )


async def upsert_address(
    session: "AsyncSession",
    *,
    customer_id: int,
    latitude: float | None,
    longitude: float | None,
    room_apartment: str,
    building: str,
    receiver_name: str | None = None,
    additional_details: str | None = None,
    confirmed: bool = False,
) -> CustomerAddress:
    # One address per customer: overwrite the existing row in place instead of
    # appending a new one. When a customer shares a new current-location pin /
    # address, the old saved address is fully replaced (pin, room, building,
    # receiver) — so "use saved address" next time offers the latest one and the
    # DB never accumulates stale duplicates. We update the same row get_last_address
    # would surface (most recently used) so both functions agree on "the" address.
    addr = await session.scalar(
        select(CustomerAddress)
        .where(CustomerAddress.customer_id == customer_id)
        .order_by(CustomerAddress.last_used_at.desc().nullslast(), CustomerAddress.id.desc())
        .limit(1)
    )
    if addr is None:
        addr = CustomerAddress(customer_id=customer_id)
        session.add(addr)
    addr.latitude = latitude
    addr.longitude = longitude
    addr.room_apartment = room_apartment
    addr.building = building
    addr.receiver_name = receiver_name
    addr.additional_details = additional_details
    addr.confirmed = confirmed
    await session.flush()

    # The WhatsApp flow only ever asks "who should the rider ask for?", never a
    # separate customer name — so backfill the customer's display name from the
    # receiver name when they don't have one yet. Otherwise the dashboard's
    # Customer column stays blank. Existing name is never overwritten.
    if receiver_name and receiver_name.strip():
        customer = await session.get(Customer, customer_id)
        if customer is not None and not (customer.name or "").strip():
            customer.name = receiver_name.strip()
            await session.flush()

    return addr


async def compute_customer_order_stats(
    session: "AsyncSession", customer_ids: list[int]
) -> dict[int, dict]:
    """Live per-customer order stats straight from the orders table.

    The denormalized Customer.total_orders / total_spend / first_order_at /
    last_order_at columns are NOT maintained anywhere, so they're always their
    creation defaults (0 / None). The orders table is the single source of
    truth: total_orders counts non-draft orders, total_spend sums delivered
    orders only (COD actually collected), and the timestamps span non-draft
    orders. Returns {} for unknown ids (caller defaults to zeros).
    """
    if not customer_ids:
        return {}
    placed = Order.status != "draft"
    rows = (await session.execute(
        select(
            Order.customer_id,
            func.count(Order.id).filter(placed),
            func.coalesce(func.sum(Order.total).filter(Order.status == "delivered"), 0),
            func.min(Order.created_at).filter(placed),
            func.max(Order.created_at).filter(placed),
        )
        .where(Order.customer_id.in_(customer_ids))
        .group_by(Order.customer_id)
    )).all()
    return {
        cid: {
            "total_orders": cnt or 0,
            "total_spend": Decimal(str(spend or 0)),
            "first_order_at": first,
            "last_order_at": last,
        }
        for cid, cnt, spend, first, last in rows
    }


def _circular_stats(hours: list[float]) -> tuple[float, float] | None:
    """Circular mean of hours-of-day → ``(mean_hour, R)`` or None if empty.

    Treats the 24h clock as a circle so times straddling midnight (23:30 +
    00:30) average to ~00:00, not noon. ``R`` (resultant length, 0..1) measures
    how clustered the times are.
    """
    if not hours:
        return None
    angles = [h / 24.0 * 2 * math.pi for h in hours]
    mean_sin = sum(math.sin(a) for a in angles) / len(angles)
    mean_cos = sum(math.cos(a) for a in angles) / len(angles)
    mean_angle = math.atan2(mean_sin, mean_cos)
    mean_hour = (mean_angle / (2 * math.pi) * 24.0) % 24.0
    resultant = math.hypot(mean_sin, mean_cos)
    return mean_hour, resultant


def _format_usual_order_time(hours: list[float]) -> str | None:
    """Human label for when a customer typically orders, e.g. "Evenings (~8:20 PM)".

    `hours` are local (Asia/Dubai) hours-of-day as floats (hour + minute/60).
    Returns None if there's no data.
    """
    stats = _circular_stats(hours)
    if stats is None:
        return None
    mean_hour, _ = stats

    h = int(mean_hour)
    m = int(round((mean_hour - h) * 60))
    if m == 60:
        h = (h + 1) % 24
        m = 0
    if 5 <= h < 12:
        daypart = "Mornings"
    elif 12 <= h < 17:
        daypart = "Afternoons"
    elif 17 <= h < 21:
        daypart = "Evenings"
    else:
        daypart = "Late night"
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{daypart} (~{h12}:{m:02d} {suffix})"


async def _order_created_rows(
    session: "AsyncSession", customer_id: int
) -> list[tuple[datetime | None, ...]]:
    rows = (
        await session.scalars(
            select(Order.created_at).where(
                Order.customer_id == customer_id,
                Order.status != "draft",
            )
        )
    ).all()
    return [(r,) for r in rows]


async def _order_stamps_dubai(
    session: "AsyncSession", customer_id: int, *, now_utc: datetime | None = None
):
    """Recency-aware Dubai order stamps for habit prediction."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    return order_stamps_from_rows(
        await _order_created_rows(session, customer_id), now_utc=now_utc
    )


async def _order_hours_dubai(session: "AsyncSession", customer_id: int) -> list[float]:
    """Local (Asia/Dubai) hour-of-day floats for a customer's non-draft orders."""
    stamps = await _order_stamps_dubai(session, customer_id)
    return [s.hour for s in stamps]


async def compute_usual_order_time(
    session: "AsyncSession", customer_id: int
) -> str | None:
    """Typical local time-of-day this customer places orders (None if no orders)."""
    return _format_usual_order_time(await _order_hours_dubai(session, customer_id))


async def predict_order_time(
    session: "AsyncSession",
    customer_id: int,
    *,
    weekday: int | None = None,
) -> OrderTimePrediction | None:
    """Numeric prediction of a customer's usual order time (None if no orders).

    When ``weekday`` is set (0=Mon, Dubai local), only orders on that weekday
    feed the estimate — Friday lunch habits stay separate from Saturday dinner.
    Recency-weighted so habit drift tracks recent behaviour.
    """
    stamps = await _order_stamps_dubai(session, customer_id)
    return predict_from_stamps(stamps, weekday=weekday, apply_recency=True)


async def recompute_customer_stats(session: "AsyncSession", customer_id: int) -> None:
    """Refresh a customer's denormalized order stats from the orders table.

    Idempotent — it RE-DERIVES the totals rather than incrementing, so it can
    be called after any order transition without drift. Marketing segments
    (marketing/segments.py) query these columns directly in SQL, so they must
    stay in sync as orders progress. Called from fsm.transition and
    dispatch.advance_delivery (the two order status chokepoints).
    """
    customer = await session.get(Customer, customer_id)
    if customer is None:
        return
    stats = (await compute_customer_order_stats(session, [customer_id])).get(customer_id)
    customer.total_orders = stats["total_orders"] if stats else 0
    customer.total_spend = stats["total_spend"] if stats else Decimal("0.00")
    customer.first_order_at = stats["first_order_at"] if stats else None
    customer.last_order_at = stats["last_order_at"] if stats else None
    customer.usual_order_time = await compute_usual_order_time(session, customer_id)
    now_utc = datetime.now(timezone.utc)
    stamps = await _order_stamps_dubai(session, customer_id, now_utc=now_utc)
    customer.usual_order_times = build_usual_order_times(stamps, now_utc=now_utc)
    await session.flush()


# Namespace for the per-restaurant order-number allocation advisory lock (arbitrary
# constant, distinct from the dispatch lock's namespace, so the two never collide).
_ORDER_NUMBER_LOCK_CLASS = 4_919_002


async def create_draft_order(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
) -> Order:
    """Create a draft order with a unique, atomically-allocated per-tenant order number.

    TX-13/F114: a plain ``count() + 1`` allocation races when two inbound messages
    for the same (or different) customers create draft orders concurrently — both
    read the same count and mint the same ``order_number``, which used to surface
    as duplicate ``#R1-0001`` order numbers in production transcripts. We serialize
    allocation per restaurant with a transaction-scoped Postgres advisory lock (best
    effort — a non-Postgres test backend just proceeds unserialized), and the DB
    ``UniqueConstraint(restaurant_id, order_number)`` is the hard backstop: on a
    collision we retry allocation inside a SAVEPOINT rather than aborting the whole
    caller transaction.
    """
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError

    try:
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:c, :o)"),
            {"c": _ORDER_NUMBER_LOCK_CLASS, "o": restaurant_id},
        )
    except Exception:  # noqa: BLE001 — non-Postgres backend; proceed without the lock
        _logger.debug("advisory order-number lock unavailable; proceeding unserialized")

    # Allocate from the HIGHEST existing suffix, not count(): deleted / resold /
    # cleaned-up drafts leave gaps, so count()+1 can land on a suffix that a live
    # order already owns (prod: count=120 but R1-0121 exists → collision). Scanning
    # the numeric suffixes and taking max+1 is gap-proof; the advisory lock above
    # serializes concurrent allocators and the UniqueConstraint retry is the backstop.
    base_seq = await _next_order_seq(session, restaurant_id)

    last_error: IntegrityError | None = None
    for _attempt in range(5):
        order_number = f"R{restaurant_id}-{base_seq + _attempt:04d}"
        order = Order(
            restaurant_id=restaurant_id,
            customer_id=customer_id,
            order_number=order_number,
            status=OrderStatus.DRAFT,
            priority="normal",
            weather_delay_disclosed=False,
            delivery_fee_aed=Decimal("0.00"),
            subtotal=Decimal("0.00"),
            total=Decimal("0.00"),
        )
        session.add(order)
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as exc:
            # The savepoint rollback already detaches `order`; calling expunge()
            # unconditionally raises InvalidRequestError ("not present in this
            # Session"), which used to escape this handler and abort the whole
            # retry (the real prod crash). Guard it and keep retrying.
            if order in session:
                session.expunge(order)
            last_error = exc
            continue
        return order

    raise RuntimeError(
        f"could not allocate a unique order number for restaurant {restaurant_id}"
    ) from last_error


async def _next_order_seq(session: "AsyncSession", restaurant_id: int) -> int:
    """Next per-tenant order sequence = 1 + the highest numeric suffix currently in use.

    Order numbers are ``R{restaurant_id}-{seq:04d}``. We derive the next seq from the
    MAX existing suffix rather than a row count so gaps (deleted drafts, resold /
    excluded orders) never cause a collision with a live number. Portable across
    backends — parses suffixes in Python instead of relying on SPLIT_PART.
    """
    numbers = await session.scalars(
        select(Order.order_number).where(Order.restaurant_id == restaurant_id)
    )
    max_seq = 0
    for number in numbers:
        try:
            max_seq = max(max_seq, int(str(number).rsplit("-", 1)[-1]))
        except (ValueError, IndexError):
            continue  # legacy / malformed number — ignore for allocation
    return max_seq + 1


def _effective_unit_price(dish: "Dish", variant: dict | None = None) -> Decimal:
    """Price charged for one unit of a cart line.

    A chosen serving-size variant carries its own price. Otherwise the flat dish is
    charged at its SALE price when one is set and valid (0 < sale < base) — so a dish
    on sale (e.g. Mojito base 40 / sale 20) is added to the cart at 20, not 40. Falls
    back to the base price when there's no sale price.
    """
    if variant:
        return Decimal(str(variant["price_aed"]))
    base = dish.price_aed
    sale = getattr(dish, "sale_price_aed", None)
    if sale is not None:
        sale_dec = Decimal(str(sale))
        if sale_dec > 0 and (base is None or sale_dec < base):
            return sale_dec
    return base


async def add_item(
    session: "AsyncSession",
    *,
    order: Order,
    dish: "Dish",
    qty: int = 1,
    notes: str | None = None,
    variant: dict | None = None,
    price_aed_override: Decimal | None = None,
) -> OrderItem:
    # When a serving-size variant is chosen, snapshot its name + price; otherwise the
    # dish is charged at its sale price when set (else base price). A caller may pass
    # ``price_aed_override`` to snapshot an externally-authoritative unit price (e.g. the
    # tapped Meta catalogue ``item_price``) instead of the local Dish.price_aed (R-051).
    variant_name = variant.get("name") if variant else None
    if price_aed_override is not None and variant is None:
        unit_price = Decimal(str(price_aed_override))
    else:
        unit_price = _effective_unit_price(dish, variant)

    # Merge into an existing line for the same dish + variant + notes so the cart shows
    # "2x Mango Lassi" instead of two separate "1x" lines (matches how real ordering
    # apps present a cart). A different variant is a separate line.
    existing_line = (
        await session.scalars(
            select(OrderItem).where(
                OrderItem.order_id == order.id,
                OrderItem.dish_id == dish.id,
                OrderItem.variant_name.is_(variant_name)
                if variant_name is None
                else OrderItem.variant_name == variant_name,
            )
        )
    ).first()
    if existing_line is not None:
        existing_line.qty += qty
        # Non-empty incoming note wins; empty preserves existing (R-002)
        if notes:
            existing_line.notes = notes
        item = existing_line
    else:
        item = OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=dish.dish_number,
            dish_name=dish.name,
            variant_name=variant_name,
            price_aed=unit_price,
            qty=qty,
            notes=notes,
        )
        session.add(item)
    await session.flush()
    # Recalculate order totals from persisted items.
    existing = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    subtotal = sum((i.price_aed * i.qty for i in existing), Decimal("0.00"))
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()
    return item


async def remove_item(
    session: "AsyncSession",
    *,
    order: Order,
    dish: "Dish",
    qty: int = 1,
) -> int:
    """Remove up to ``qty`` units of ``dish`` from ``order``; return units removed.

    Decrements existing line items for the dish (newest first). Lines that reach
    zero are deleted. Recalculates order totals. Returns 0 if the dish is not in
    the cart. Caller commits.
    """
    items = (
        await session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order.id, OrderItem.dish_id == dish.id)
            .order_by(OrderItem.id.desc())
        )
    ).all()

    remaining = max(0, qty)
    removed = 0
    for item in items:
        if remaining <= 0:
            break
        take = min(item.qty, remaining)
        item.qty -= take
        removed += take
        remaining -= take
        if item.qty <= 0:
            await session.delete(item)
    if removed == 0:
        return 0
    await session.flush()

    existing = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    subtotal = sum((i.price_aed * i.qty for i in existing), Decimal("0.00"))
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()
    return removed


async def set_item_qty(
    session: "AsyncSession",
    *,
    order: Order,
    dish_id: int,
    qty: int,
    variant_name: str | None = None,
) -> OrderItem | None:
    """Set the quantity of ``dish_id`` in ``order`` to exactly ``qty``.

    Collapses any duplicate lines for the dish into one. ``qty <= 0`` removes
    the dish entirely. Recalculates totals. Returns the surviving line (or None
    if the dish was not in the cart, or was removed). Caller commits.

    Used by the "make it 3" / "change to 2" context-update intercept.
    """
    conditions = [OrderItem.order_id == order.id, OrderItem.dish_id == dish_id]
    if variant_name is not None:
        conditions.append(OrderItem.variant_name == variant_name)
    items = (
        await session.scalars(
            select(OrderItem).where(*conditions).order_by(OrderItem.id)
        )
    ).all()
    if not items:
        return None

    survivor: OrderItem | None = None
    if qty <= 0:
        for item in items:
            await session.delete(item)
    else:
        # Prefer the line with a non-empty note as the survivor (R-006/RA-7)
        noted = next((i for i in items if (i.notes or "").strip()), None)
        survivor = noted if noted is not None else items[0]
        survivor.qty = qty
        for item in items:
            if item.id != survivor.id:
                await session.delete(item)
    await session.flush()

    remaining = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    subtotal = sum((i.price_aed * i.qty for i in remaining), Decimal("0.00"))
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()
    return survivor


async def set_item_note(
    session: "AsyncSession",
    *,
    order: Order,
    dish_id: int,
    notes: str,
    qty: int | None = None,
) -> OrderItem | None:
    """Move an existing cart dish to a kitchen-note line and merge duplicates.

    Special requests are line-level state. When a customer says "no onion on the
    biryani" after the biryani is already in the cart, that should update the
    existing line rather than add another paid biryani. ``qty`` optionally sets
    the final total quantity for the noted line.
    """
    clean_notes = (notes or "").strip()
    if not clean_notes:
        return None

    items = (
        await session.scalars(
            select(OrderItem)
            .where(OrderItem.order_id == order.id, OrderItem.dish_id == dish_id)
            .order_by(OrderItem.id)
        )
    ).all()
    if not items:
        return None

    survivor = next((i for i in items if (i.notes or "").strip() == clean_notes), items[0])
    survivor.notes = clean_notes
    survivor.qty = max(1, qty) if qty is not None else sum(i.qty for i in items)
    for item in items:
        if item.id != survivor.id:
            await session.delete(item)
    await session.flush()

    remaining = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    subtotal = sum((i.price_aed * i.qty for i in remaining), Decimal("0.00"))
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()
    return survivor


def parse_qty_and_text(text: str) -> tuple[int, str]:
    """Parse quantity prefixes from free text. Returns (qty, remaining_text).

    Handles: "2x chicken", "x2 chicken", "two chicken", "2 chicken",
    "make it 2 chicken", "chicken" (qty=1).
    """
    text = text.strip()
    m = re.match(r"^(\d+)\s*[xX]\s*(.+)$", text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    m = re.match(r"^[xX]\s*(\d+)\s+(.+)$", text)
    if m:
        return int(m.group(1)), m.group(2).strip()
    word_map = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    }
    lower = text.lower()
    for word, val in word_map.items():
        if lower.startswith(word + " "):
            return val, text[len(word):].strip()
    # "2 201" — qty followed by a bare dish number (3+ digits)
    m = re.match(r"^(\d+)\s+(\d{3,})$", text)
    if m:
        qty = int(m.group(1))
        if 1 <= qty <= 20:
            return qty, m.group(2)

    # Natural: "2 biryani" / "make it 2 biryani" / "1 चिकन बिरयानी" / "2 బిర్యానీ" —
    # qty followed by a dish name in ANY script. Use \D (any non-digit) so it's not
    # limited to Latin+Arabic; otherwise Hindi/Telugu/etc. left the qty in the query.
    m = re.search(r"\b(\d+)\s+(\D.*)$", text)
    if m:
        qty = int(m.group(1))
        if 1 <= qty <= 20:  # dish numbers are 100+ so small ints are quantities
            return qty, m.group(2).strip()
    return 1, text


async def finalize_confirmation(
    session: "AsyncSession",
    *,
    order: Order,
    actor: str = "customer",
) -> None:
    """Move order draft → pending_confirmation → confirmed and start the SLA clock.

    Idempotent: a replay on an anything-but-unconfirmed order is a pure no-op.
    Without the guard, a second call silently RESTARTED the SLA clock,
    re-applied the wallet hold and re-pushed to the partner. Modification's
    SLA restart is deliberate and lives in its own path (confirm_modification),
    never here.
    """
    if order.status not in (OrderStatus.DRAFT, OrderStatus.PENDING_CONFIRMATION):
        return
    if order.status == OrderStatus.DRAFT:
        await fsm_transition(session, order, OrderStatus.PENDING_CONFIRMATION, actor=actor)
    if order.status == OrderStatus.PENDING_CONFIRMATION:
        await fsm_transition(session, order, OrderStatus.CONFIRMED, actor=actor)
    now = datetime.now(timezone.utc)
    order.sla_confirmed_at = now
    order.sla_deadline = now + timedelta(minutes=40)
    order.promised_eta = order.sla_deadline
    order.prep_deadline = await compute_prep_deadline(session, order, now)
    order.cook_estimate_minutes = await compute_cook_estimate(session, order)

    from app.ordering.tax import apply_vat

    apply_vat(order)

    # Auto-apply any available wallet store credit: holds it against this order so
    # COD due = total - wallet_applied (settled on delivery, released on cancel).
    from app.ordering.payments import apply_at_confirm

    await apply_at_confirm(session, order=order, use_wallet=True, created_by=actor)
    from app.partner.orders_api import push_order_to_partner

    await push_order_to_partner(session, order=order)

    from app.kds.service import create_tickets_for_order

    await create_tickets_for_order(session, restaurant_id=order.restaurant_id, order=order)

    from app.inventory.service import deduct_for_order

    await deduct_for_order(session, restaurant_id=order.restaurant_id, order=order)
    await session.flush()


# Statuses at/after which the kitchen is locked in — modification is forbidden.
_NON_MODIFIABLE_STATUSES = {
    OrderStatus.READY,
    OrderStatus.ASSIGNED,
    OrderStatus.PICKED_UP,
    OrderStatus.ARRIVING,
    OrderStatus.DELIVERED,
    OrderStatus.CANCELLED,
    OrderStatus.UNDELIVERABLE,
    OrderStatus.ON_RESALE,
    OrderStatus.RESOLD,
    OrderStatus.WRITTEN_OFF,
}


async def modify_order(
    session: "AsyncSession",
    *,
    order: Order,
    new_items: list[dict],
    actor: str,
) -> None:
    """Replace all items on an order, recalculate totals, restart the SLA clock.

    Allowed only before status reaches 'ready' (spec §4.5). Once the customer
    confirms the modification the 40-minute clock restarts. Caller must commit.
    """
    if order.status in _NON_MODIFIABLE_STATUSES:
        raise ValueError(
            f"Order modification not allowed at status '{order.status}'. "
            f"Modifications are blocked once an order reaches 'ready'."
        )

    before_snapshot = {
        "status": str(order.status),
        "subtotal": str(order.subtotal),
        "total": str(order.total),
        "sla_deadline": order.sla_deadline.isoformat() if order.sla_deadline else None,
    }

    existing_items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    for item in existing_items:
        await session.delete(item)
    await session.flush()

    subtotal = Decimal("0.00")
    for entry in new_items:
        dish = entry["dish"]
        qty = entry.get("qty", 1)
        notes = entry.get("notes")
        variant_name = entry.get("variant_name")
        if entry.get("price_aed") is not None:
            unit_price = Decimal(str(entry["price_aed"]))
        else:
            unit_price = _effective_unit_price(dish)
        item = OrderItem(
            order_id=order.id,
            dish_id=dish.id,
            dish_number=dish.dish_number,
            dish_name=dish.name,
            variant_name=variant_name,
            price_aed=unit_price,
            qty=qty,
            notes=notes,
        )
        session.add(item)
        subtotal += unit_price * qty

    await session.flush()
    # Re-derive subtotal/total from the persisted items and RE-APPLY the coupon
    # discount + wallet hold (F26) — never a bare subtotal+fee that drops payments.
    from app.ordering.payments import recompute_order_total

    await recompute_order_total(session, order=order)

    # Restart the SLA clock after the customer confirms the modification.
    now = datetime.now(timezone.utc)
    order.sla_confirmed_at = now
    order.sla_deadline = now + timedelta(minutes=40)
    order.promised_eta = order.sla_deadline
    order.prep_deadline = await compute_prep_deadline(session, order, now)
    order.cook_estimate_minutes = await compute_cook_estimate(session, order)
    await session.flush()

    await record_audit(
        session,
        actor=actor,
        restaurant_id=order.restaurant_id,
        entity="order",
        entity_id=str(order.id),
        action="order_modified",
        before=before_snapshot,
        after={
            "subtotal": str(order.subtotal),
            "total": str(order.total),
            "sla_deadline": order.sla_deadline.isoformat(),
        },
    )


async def _recompute_totals_excluding_cancelled(session: "AsyncSession", order: Order) -> None:
    """Recompute subtotal/total from persisted, non-cancelled items (add_item/remove_item
    pattern — no coupon/wallet re-application here, matching those existing helpers)."""
    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()
    subtotal = sum(
        (i.price_aed * i.qty for i in items if not i.cancelled), Decimal("0.00")
    )
    order.subtotal = subtotal
    order.total = subtotal + order.delivery_fee_aed
    await session.flush()


async def _get_order_item_for_tenant(
    session: "AsyncSession", *, restaurant_id: int, order_id: int, order_item_id: int
) -> tuple[Order, OrderItem]:
    """Fetch (order, item) scoped to the tenant. Raises ValueError if either is missing
    or the item does not belong to the order."""
    order = await get_order_for_tenant(session, restaurant_id=restaurant_id, order_id=order_id)
    if order is None:
        raise ValueError("Order not found")
    item = await session.get(OrderItem, order_item_id)
    if item is None or item.order_id != order.id:
        raise ValueError("Order item not found")
    return order, item


def _assert_order_modifiable(order: Order) -> None:
    if order.status in _NON_MODIFIABLE_STATUSES:
        raise ValueError(
            f"Order modification not allowed at status '{order.status}'. "
            f"Modifications are blocked once an order reaches 'ready'."
        )


async def cancel_order_item(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    order_id: int,
    order_item_id: int,
    reason: str | None,
    actor: str,
) -> OrderItem:
    """Cancel a single line item on an order (partial cancellation), without voiding
    the whole order. Allowed only before the order reaches 'ready' (same gate as
    ``modify_order``). Recomputes subtotal/total excluding cancelled items. Caller commits.
    """
    order, item = await _get_order_item_for_tenant(
        session, restaurant_id=restaurant_id, order_id=order_id, order_item_id=order_item_id
    )
    _assert_order_modifiable(order)
    if item.cancelled:
        raise ValueError("Order item is already cancelled")

    before_snapshot = {
        "qty": item.qty,
        "cancelled": item.cancelled,
        "subtotal": str(order.subtotal),
        "total": str(order.total),
    }

    item.cancelled = True
    item.cancelled_reason = reason
    await session.flush()

    await _recompute_totals_excluding_cancelled(session, order)

    await record_audit(
        session,
        actor=actor,
        restaurant_id=order.restaurant_id,
        entity="order_item",
        entity_id=str(item.id),
        action="order_item_cancelled",
        before=before_snapshot,
        after={
            "cancelled": True,
            "cancelled_reason": reason,
            "subtotal": str(order.subtotal),
            "total": str(order.total),
        },
    )
    return item


async def edit_order_item(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    order_id: int,
    order_item_id: int,
    new_qty: int | None,
    new_notes: str | None,
    actor: str,
) -> OrderItem:
    """Edit qty and/or notes on an existing (unfired) line item, only while the order is
    still pre-'ready' (same gate as ``modify_order``). Recomputes totals when qty changes.
    Caller commits.
    """
    order, item = await _get_order_item_for_tenant(
        session, restaurant_id=restaurant_id, order_id=order_id, order_item_id=order_item_id
    )
    _assert_order_modifiable(order)
    if item.cancelled:
        raise ValueError("Cannot edit a cancelled order item")
    if new_qty is not None and new_qty <= 0:
        raise ValueError("Quantity must be at least 1")

    before_snapshot = {
        "qty": item.qty,
        "notes": item.notes,
        "subtotal": str(order.subtotal),
        "total": str(order.total),
    }

    qty_changed = new_qty is not None and new_qty != item.qty
    if new_qty is not None:
        item.qty = new_qty
    if new_notes is not None:
        item.notes = new_notes
    await session.flush()

    if qty_changed:
        await _recompute_totals_excluding_cancelled(session, order)

    await record_audit(
        session,
        actor=actor,
        restaurant_id=order.restaurant_id,
        entity="order_item",
        entity_id=str(item.id),
        action="order_item_edited",
        before=before_snapshot,
        after={
            "qty": item.qty,
            "notes": item.notes,
            "subtotal": str(order.subtotal),
            "total": str(order.total),
        },
    )
    return item


# Customer self-cancel via WhatsApp — only before the order leaves the kitchen flow.
_CUSTOMER_CANCELLABLE_STATUSES = {
    OrderStatus.DRAFT,
    OrderStatus.PENDING_CONFIRMATION,
    OrderStatus.CONFIRMED,
    OrderStatus.PREPARING,
}

# Restaurant/manager/POS may cancel any active order until delivery.
_RESTAURANT_CANCEL_ACTORS = frozenset({"manager", "pos", "restaurant"})


async def _emit_cancel_side_effects(
    session: "AsyncSession",
    *,
    order: Order,
    actor: str,
    reason: str | None,
) -> None:
    """Best-effort customer WhatsApp + partner ``order.cancelled`` webhook.

    Customer-initiated cancels are messaged by the conversation engine — skip the
    duplicate outbox ping here. Restaurant/POS/manager paths must notify because
    the dashboard and partner APIs do not go through ``engine._execute_cancel_order``.
    """
    if actor in _RESTAURANT_CANCEL_ACTORS:
        try:
            from app.dispatch.rider_flow import _notify_customer_status

            await _notify_customer_status(
                session,
                restaurant_id=order.restaurant_id,
                order=order,
                status_key="cancelled",
            )
        except Exception:  # noqa: BLE001 — never block the cancel
            _logger.exception("customer cancel notify failed (order_id=%s)", order.id)

    try:
        from app.partner.delivery_api import notify_partner_delivery_event

        extra: dict = {"cancelled_by": actor}
        if reason:
            extra["cancellation_reason"] = reason
        if order.cancelled_at is not None:
            extra["cancelled_at"] = order.cancelled_at.isoformat()
        await notify_partner_delivery_event(
            session,
            order=order,
            event_type="order.cancelled",
            extra=extra,
        )
    except Exception:  # noqa: BLE001
        _logger.exception("partner cancel webhook failed (order_id=%s)", order.id)


async def cancel_order(
    session: "AsyncSession",
    *,
    order: Order,
    actor: str,
    reason: str | None = None,
) -> Order | None:
    """Cancel an order.

    Resale (re-offer the cooked food to the next customer) happens ONLY when the
    CUSTOMER cancels an order that's already cooking — the food exists and is fine, the
    customer just backed out. When the RESTAURANT/manager cancels, the food is assumed
    unavailable or unfit (out of stock, kitchen issue, bad batch), so it is NOT resold —
    plain transition to CANCELLED.

    So: customer cancel while ``preparing`` → ON_RESALE + resale copy (exclusion hash).
    Any other cancel (pre-cooking, or restaurant-initiated) → CANCELLED.

    Restaurant/POS/manager may cancel through ``arriving`` (inclusive). Customers may
    only cancel through ``preparing``. ``delivered`` and terminal states reject all actors.

    Returns the resale Order if one was created, else None. Caller must commit.
    """
    if actor == "customer" and order.status not in _CUSTOMER_CANCELLABLE_STATUSES:
        raise IllegalTransitionError(
            f"Customer cannot cancel order in status {order.status!r}. "
            f"Allowed: {sorted(s.value for s in _CUSTOMER_CANCELLABLE_STATUSES)}"
        )
    if actor not in _RESTAURANT_CANCEL_ACTORS and actor != "customer":
        raise IllegalTransitionError(f"Unknown cancel actor {actor!r}")

    order.cancellation_reason = reason
    order.cancelled_at = datetime.now(timezone.utc)

    # Return any wallet credit held against this order (no-op if none).
    from app.ordering.payments import release_on_cancel

    await release_on_cancel(session, order=order)

    # Claw back any loyalty credit earned on this order (no-op if none / not earned).
    # Covers cancelling a delivered order that already triggered earn. Best-effort —
    # never block the cancel.
    try:
        from app.loyalty.service import reverse_earn

        await reverse_earn(session, order=order)
    except Exception:  # noqa: BLE001
        pass

    # If a rider was already assigned/batched, detach the order from dispatch so the
    # rider stops being told to collect/deliver cancelled food (frees rider, stops
    # tracking, pushes the cancellation). No-op if never dispatched. Best-effort.
    try:
        from app.dispatch.service import release_order_from_dispatch

        await release_order_from_dispatch(session, order=order, actor=actor)
    except Exception:  # noqa: BLE001 — never block the cancel
        pass

    if order.status == OrderStatus.PREPARING and actor == "customer":
        await fsm_transition(
            session, order, OrderStatus.ON_RESALE, actor=actor,
            extra_audit={"reason": reason or ""},
        )

        customer = await session.get(Customer, order.customer_id)
        phone = customer.phone if customer else ""
        # AND-gate exclusion: bar re-delivery only when phone + door/apartment + building +
        # pinned location ALL match the canceller's (so the same person can't game it at the
        # same address, but every other customer/address can still buy the food).
        room = building = ""
        lat = lon = None
        if order.address_id is not None:
            address = await session.get(CustomerAddress, order.address_id)
            if address is not None:
                room = (address.room_apartment or "").strip().lower()
                building = (address.building or "").strip().lower()
                lat, lon = address.latitude, address.longitude
        exclusion_hash = _compute_exclusion_hash(phone, room, building, lat, lon)
        # Enforced at OFFER (matcher) and re-checked at ACCEPT (delivery guard) via
        # is_excluded_for_resale with the buyer's actual address.

        resale = Order(
            restaurant_id=order.restaurant_id,
            customer_id=order.customer_id,
            order_number=f"{order.order_number}-RS",
            status=OrderStatus.ON_RESALE,
            priority=order.priority,
            weather_delay_disclosed=order.weather_delay_disclosed,
            delivery_fee_aed=order.delivery_fee_aed,
            subtotal=order.subtotal,
            total=order.total,
            address_id=order.address_id,
            distance_km=order.distance_km,
            additional_details=order.additional_details,
            resale_of_order_id=order.id,
            exclusion_hash=exclusion_hash,
            cancelled_at=order.cancelled_at,
        )
        session.add(resale)
        await session.flush()

        # Clone the cooked line items onto the resale copy so the resold order and
        # the kitchen/rider know exactly what the food is (the copy carried totals
        # but not items, leaving resold orders empty).
        orig_items = (
            await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
        ).all()
        for it in orig_items:
            session.add(
                OrderItem(
                    order_id=resale.id, dish_id=it.dish_id, dish_number=it.dish_number,
                    dish_name=it.dish_name, variant_name=it.variant_name,
                    price_aed=it.price_aed, qty=it.qty, notes=it.notes,
                )
            )
        await session.flush()
        from app.dispatch.preview_cache import invalidate_preview_cache

        await invalidate_preview_cache(order.restaurant_id)
        await _emit_cancel_side_effects(session, order=order, actor=actor, reason=reason)
        return resale

    await fsm_transition(
        session, order, OrderStatus.CANCELLED, actor=actor,
        extra_audit={"reason": reason or ""},
    )
    from app.dispatch.preview_cache import invalidate_preview_cache

    await invalidate_preview_cache(order.restaurant_id)
    await _emit_cancel_side_effects(session, order=order, actor=actor, reason=reason)
    return None


async def delete_order(
    session: "AsyncSession", *, restaurant_id: int, order_id: int
) -> bool:
    """Hard-delete an order and every row that references it (admin/test cleanup).

    Tenant-scoped. DESTRUCTIVE — removes operational AND financial rows tied to
    the order (items, batch links, assignments, COD cash, SLA events, coupons),
    and nulls soft references (resale parent, coupon redemption, marketing
    attribution). Returns False if the order isn't this tenant's. Caller-facing
    cancellation should use cancel_order; this is for wiping test data only.
    """
    from app.cod.models import CodCollection
    from app.coupons.models import Coupon
    from app.dispatch.models import Assignment, BatchOrder
    from app.marketing.models import MarketingSend
    from app.sla.models import SlaEvent

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant_id:
        return False

    # Null nullable references so they survive without pointing at a dead order.
    await session.execute(
        sa_update(Order).where(Order.resale_of_order_id == order_id).values(resale_of_order_id=None)
    )
    await session.execute(
        sa_update(Coupon).where(Coupon.redeemed_on_order_id == order_id).values(redeemed_on_order_id=None)
    )
    await session.execute(
        sa_update(MarketingSend).where(MarketingSend.converted_order_id == order_id).values(converted_order_id=None)
    )
    # Delete hard dependents (FK-NOT-NULL).
    for model, col in (
        (OrderItem, OrderItem.order_id),
        (BatchOrder, BatchOrder.order_id),
        (Assignment, Assignment.order_id),
        (CodCollection, CodCollection.order_id),
        (SlaEvent, SlaEvent.order_id),
        (Coupon, Coupon.order_id),
    ):
        await session.execute(sa_delete(model).where(col == order_id))

    await record_audit(
        session, actor="manager", restaurant_id=restaurant_id,
        entity="order", entity_id=str(order_id), action="deleted",
        before={"order_number": order.order_number, "status": str(order.status)},
    )
    await session.delete(order)
    await session.commit()
    return True


# Manager-driven kitchen status transitions: confirmed→preparing, preparing→ready.
_KITCHEN_TRANSITIONS: dict[OrderStatus, OrderStatus] = {
    OrderStatus.CONFIRMED: OrderStatus.PREPARING,
    OrderStatus.PREPARING: OrderStatus.READY,
}


async def advance_kitchen_status(
    session: "AsyncSession",
    *,
    order: Order,
    actor: str = "manager",
) -> Order:
    """Advance order through kitchen FSM: confirmed→preparing or preparing→ready.

    Raises ValueError if the order is not in a kitchen-advanceable state.
    """
    next_status = _KITCHEN_TRANSITIONS.get(OrderStatus(order.status))
    if next_status is None:
        raise ValueError(
            f"Cannot advance kitchen status from '{order.status}'. "
            f"Only confirmed or preparing orders can be advanced."
        )
    await fsm_transition(session, order, next_status, actor=actor)
    # When the kitchen starts the dish, refresh the plate-by deadline from current
    # delivery inputs (a re-pinned address or live traffic may have moved it since
    # confirm) and warn the kitchen if it just got tighter.
    if next_status == OrderStatus.PREPARING:
        await _refresh_prep_deadline(session, order)
        from app.dispatch.rider_flow import _notify_customer_status

        await _notify_customer_status(
            session,
            restaurant_id=order.restaurant_id,
            order=order,
            status_key="preparing",
        )
    await session.commit()
    await session.refresh(order)
    # Event-driven dispatch: as soon as an order is READY, assign a rider — no
    # manual /dispatch/trigger and no Celery beat required (this runs in the
    # web request that marked it ready). Best-effort: never break the kitchen
    # action if dispatch fails.
    if order.status == "ready":
        await _auto_dispatch_on_ready(session, order.restaurant_id)
    from app.dispatch.preview_cache import invalidate_preview_cache

    await invalidate_preview_cache(order.restaurant_id)
    return order


async def _refresh_prep_deadline(session: "AsyncSession", order: Order) -> None:
    """Recompute prep_deadline from current inputs (clock start = sla_confirmed_at, so it
    stays absolute). If the new plate-by is more than 5 min EARLIER than the stored one
    — e.g. the customer re-pinned to a farther address while it was confirmed — update it
    and ping the kitchen so they can expedite. Idempotent per order per target minute."""
    base = order.sla_confirmed_at or datetime.now(timezone.utc)
    new = await compute_prep_deadline(session, order, base)
    if new is None:
        return
    old = order.prep_deadline
    if old is not None and old.tzinfo is None:
        old = old.replace(tzinfo=timezone.utc)
    order.prep_deadline = new

    if old is None or (old - new).total_seconds() <= 5 * 60:
        return  # not materially tighter — no need to nudge the kitchen

    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is None:
        return
    local = new.astimezone(ZoneInfo("Asia/Dubai"))
    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    await enqueue_message(
        session,
        restaurant_id=order.restaurant_id,
        to_phone=restaurant.phone,
        msg_type=OutboundMessageType.TEXT,
        payload={
            "body": (
                f"⏱️ Heads up — order {order.order_number} now needs to be plated by "
                f"{local:%H:%M} (the delivery got farther). Expedite to keep the 40-min SLA."
            )
        },
        idempotency_key=f"prep-tighten-{order.id}-{int(new.timestamp() // 60)}",
    )


async def _auto_dispatch_on_ready(session: "AsyncSession", restaurant_id: int) -> None:
    """Run the dispatch engine for a restaurant that just got a ready order and
    deliver the resulting rider/manager notifications. Isolated + best-effort so a
    dispatch error can't roll back the committed kitchen transition."""
    from app.dispatch.service import run_dispatch_engine
    from app.outbox.models import OutboxMessage
    from app.outbox.service import deliver_outbox_now

    try:
        await run_dispatch_engine(session, restaurant_id=restaurant_id)
        await session.commit()
    except Exception:  # noqa: BLE001 - dispatch must not break the kitchen action
        _logger.exception("auto-dispatch on ready failed (restaurant_id=%s)", restaurant_id)
        await session.rollback()
        return
    try:
        from app.partner.webhooks.dispatch import flush_pending_partner_webhooks

        await flush_pending_partner_webhooks(session, restaurant_id=restaurant_id)
    except Exception:  # noqa: BLE001 - partner webhook flush is best-effort
        _logger.exception(
            "auto-dispatch partner webhook flush failed (restaurant_id=%s)",
            restaurant_id,
        )
    try:
        ids = (
            await session.scalars(
                select(OutboxMessage.id).where(
                    OutboxMessage.restaurant_id == restaurant_id,
                    OutboxMessage.status == "pending",
                )
            )
        ).all()
        await deliver_outbox_now(session, list(ids))
    except Exception:  # noqa: BLE001 - notification delivery is best-effort
        _logger.exception("auto-dispatch outbox delivery failed (restaurant_id=%s)", restaurant_id)


async def _geocode_manual_address(
    session: "AsyncSession", restaurant_id: int, building: str
) -> tuple[float | None, float | None]:
    """Best-effort geocode of a typed manual-order address to a drop-off pin.

    The manager only types a building/area (no map pin), so we resolve it to
    coordinates via the geo provider — anchored to the restaurant's area for
    accuracy. Returns ``(None, None)`` when the address is blank, geocoding is
    unavailable, or no match is found; the order then behaves as before (text
    address only, no Navigate link / destination pin).
    """
    import asyncio

    from app.geo.factory import get_geo_provider
    from app.identity.models import Restaurant

    query = (building or "").strip()
    if not query:
        return (None, None)
    try:
        restaurant = await session.get(Restaurant, restaurant_id)
        near = None
        if restaurant is not None and restaurant.lat is not None and restaurant.lng is not None:
            near = (restaurant.lat, restaurant.lng)
        # Bias to the restaurant's actual location (works in any country — the old
        # path was hard-locked to the UAE). Take the top candidate. Provider call
        # is sync (httpx); run it off the event loop.
        suggestions = await asyncio.to_thread(
            get_geo_provider().suggest, query, near=near, limit=1
        )
    except Exception:  # noqa: BLE001 - geocoding is best-effort; never block the order
        _logger.exception("manual-order geocode failed (restaurant_id=%s)", restaurant_id)
        return (None, None)
    if not suggestions:
        return (None, None)
    return (suggestions[0].latitude, suggestions[0].longitude)


async def create_manual_order(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_phone: str,
    customer_name: str | None,
    items: list[dict],
    apt_room: str,
    building: str,
    receiver_name: str,
    address_notes: str | None,
    delivery_fee_aed: Decimal,
    latitude: float | None = None,
    longitude: float | None = None,
    scheduled_for: datetime | None = None,
) -> "Order":
    """Create a confirmed delivery order on behalf of a walk-in/phone customer.

    Bypasses the WhatsApp conversation flow. Sends a WhatsApp confirmation
    via the outbox system. Caller must commit after this returns.
    """
    from app.menu.models import Dish, Menu
    from app.outbox.service import enqueue_message
    from app.whatsapp.port import OutboundMessageType

    # 1. Verify active menu exists
    menu = await session.scalar(
        select(Menu).where(
            Menu.restaurant_id == restaurant_id,
            Menu.status == "active",
        )
    )
    if not menu:
        raise ValueError("No active menu for this restaurant")

    # SAFETY GATE: never place an order with no items (an empty order the kitchen
    # cannot fulfil). The customer-facing flow gates this too; this guards the manual
    # manager path.
    if not items:
        raise ValueError("Cannot place an order with no items")

    # 2. Validate all dishes upfront
    from app.menu.service import is_dish_currently_available

    validated: list[tuple] = []
    today = datetime.now(timezone.utc).date()
    for item in items:
        dish = await session.scalar(
            select(Dish).where(
                Dish.id == item["dish_id"],
                Dish.restaurant_id == restaurant_id,
                Dish.is_available.is_(True),
            )
        )
        # Seasonal window check (Dish.available_from/available_until): the SQL filter
        # above only enforces the is_available flag, so a dish outside its seasonal
        # window (but still flagged available) is caught here too — never let a
        # manual/phone order sneak past the same rule the WhatsApp flow enforces.
        if dish is not None and not is_dish_currently_available(dish, today=today):
            dish = None
        if not dish:
            raise ValueError(f"Dish {item['dish_id']} not found or unavailable")
        validated.append((dish, item["qty"], item.get("notes")))

    # 3. Get or create customer; only set name if customer is new
    customer = await get_or_create_customer(
        session, restaurant_id=restaurant_id, phone=customer_phone
    )
    if customer_name and customer.name is None:
        customer.name = customer_name
        await session.flush()

    # 4. Store delivery address. Manual orders are typed (no GPS pin), so geocode
    #    the building text to a drop-off pin — without it the rider gets no
    #    Navigate link and the customer's tracking map has no destination. Anchor
    #    the query to the restaurant's area so an ambiguous building name resolves
    #    in the right city; degrade gracefully to no-pin if geocoding can't match.
    #    When the manager picked a suggestion in the form, use that exact pin.
    if latitude is not None and longitude is not None:
        lat, lng = latitude, longitude
    else:
        lat, lng = await _geocode_manual_address(session, restaurant_id, building)
    address = await upsert_address(
        session,
        customer_id=customer.id,
        latitude=lat,
        longitude=lng,
        room_apartment=apt_room,
        building=building,
        receiver_name=receiver_name,
        additional_details=address_notes,
        confirmed=True,
    )

    # 5. Create draft order and wire address + delivery fee
    order = await create_draft_order(
        session, restaurant_id=restaurant_id, customer_id=customer.id
    )
    order.delivery_fee_aed = delivery_fee_aed
    order.address_id = address.id
    order.scheduled_for = scheduled_for
    await session.flush()

    # 6. Add items (each call recalculates subtotal)
    for dish, qty, notes in validated:
        await add_item(session, order=order, dish=dish, qty=qty, notes=notes)

    # 7. Recompute total including delivery fee (add_item only tracks subtotal)
    order.total = order.subtotal + delivery_fee_aed
    await session.flush()

    # 8. Confirm order (draft → pending_confirmation → confirmed, starts SLA)
    await finalize_confirmation(session, order=order, actor="manager")

    # 9. Enqueue WhatsApp confirmation to customer
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=customer_phone,
        msg_type=OutboundMessageType.TEXT,
        payload={
            "body": (
                f"Your order {order.order_number} has been placed! "
                f"Total: AED {order.total} (COD). "
                f"Your food will arrive in ~40 minutes \U0001f6f5"
            )
        },
        idempotency_key=f"manual-order-confirm-{order.id}",
    )

    return order


def _chat_for_this_order(chat: list, order) -> list:
    """Restrict the chat to THIS order's session window. The conversation is per-phone
    and spans every past order, so the summary must not bleed in lines from other
    orders. Window = [order.created_at, delivered/cancelled_at or now], with a small
    lead-in so the greeting that kicked off this order is still included."""
    from datetime import datetime, timezone

    created = getattr(order, "created_at", None)
    if created is None:
        return chat  # no anchor → don't filter (better to show all than nothing)
    c = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
    lo = c.timestamp() - 120  # 2-min lead-in for the opening greeting
    end = getattr(order, "delivered_at", None) or getattr(order, "cancelled_at", None)
    if end is not None:
        e = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
        hi = e.timestamp() + 120
    else:
        hi = datetime.now(timezone.utc).timestamp()
    return [m for m in chat if lo <= getattr(m, "ts", 0) <= hi]


async def _kitchen_convo_summary(
    items_rows: list,
    *,
    order_details: str | None = None,
    delivery_details: str | None = None,
    chat: list | None = None,
) -> str | None:
    """Kitchen digest — max 3 lines.

    Tier 1 (code): item notes + persisted order/address details — authoritative.
    Tier 2 (LLM port): compress inbound chat into 0–2 net-new lines only.
    Multilingual; no phrase tables on the live path (see kitchen_summary.py)."""
    from app.llm.kitchen_summary import clamp_summary_lines, render_structured_lines

    lines = render_structured_lines(
        items_rows,
        order_details=order_details,
        delivery_details=delivery_details,
    )
    structured_block = "\n".join(lines)

    inbound = [
        (getattr(m, "text", None) or "").strip()
        for m in (chat or [])
        if getattr(m, "direction", None) == "inbound"
    ]
    inbound = [t for t in inbound if t]

    if inbound:
        try:
            from app.llm.factory import get_kitchen_summarizer

            extras = await get_kitchen_summarizer().supplement_from_chat(
                structured_block, inbound
            )
        except Exception:
            _logger.exception("kitchen summary tier-2 failed; using structured only")
            extras = []
        blob = structured_block.lower()
        for extra in extras:
            e = extra.strip()
            if e and e.lower() not in blob:
                lines.append(e)
                blob += f" {e.lower()}"

    return clamp_summary_lines(lines)


def parse_detail_includes(include: str | None) -> frozenset[str] | None:
    """Parse ``?include=`` for order detail. None means all sections."""
    if include is None:
        return None
    raw = include.strip().lower()
    if raw in ("", "all", "*"):
        return None
    parts = {p.strip() for p in raw.split(",") if p.strip()}
    return parts | {"overview"}


def _detail_wants(section: str, includes: frozenset[str] | None) -> bool:
    return includes is None or section in includes


async def get_order_detail(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    order_id: int,
    includes: frozenset[str] | None = None,
) -> OrderDetailOut:
    """Assemble order detail for the manager drawer.

    ``includes=None`` loads every section (tests). HTTP defaults to overview-only
    via ``parse_detail_includes`` in the router.
    """
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.audit.models import AuditLog
    from app.conversation.models import Conversation, Message
    from app.dispatch.models import Assignment, RiderLocation
    from app.identity.models import Rider
    from app.marketing.optout import is_opted_out
    from app.ordering.detail_schemas import (
        AddressDetailOut,
        ChatMessageOut,
        CustomerDetailOut,
        GpsPingOut,
        OrderDetailOut,
        OrderItemDetailOut,
        RiderDetailOut,
        TimelineEventOut,
    )

    # 1. Order — raise if wrong tenant or unknown id
    order = await session.scalar(
        select(Order).where(Order.id == order_id, Order.restaurant_id == restaurant_id)
    )
    if not order:
        raise ValueError("Order not found")

    # 2. Items
    items_rows = list(
        (await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))).all()
    )
    items = [
        OrderItemDetailOut(
            dish_number=i.dish_number,
            dish_name=i.dish_name,
            variant_name=i.variant_name,
            qty=i.qty,
            price_aed=i.price_aed,
            notes=i.notes,
        )
        for i in items_rows
    ]

    # 3. Customer
    customer = await session.get(Customer, order.customer_id)
    if not customer:
        raise ValueError("Order not found")

    # 4. Address
    address: AddressDetailOut | None = None
    if order.address_id:
        addr = await session.get(CustomerAddress, order.address_id)
        if addr:
            address = AddressDetailOut(
                id=addr.id,
                room_apartment=addr.room_apartment,
                building=addr.building,
                receiver_name=addr.receiver_name,
                additional_details=addr.additional_details,
                latitude=addr.latitude,
                longitude=addr.longitude,
            )

    # 5. Rider
    rider: RiderDetailOut | None = None
    if order.rider_id:
        r = await session.get(Rider, order.rider_id)
        if r:
            rider = RiderDetailOut(id=r.id, name=r.name, phone=r.phone)

    assignment = None
    if _detail_wants("route", includes) or _detail_wants("dispatch", includes):
        assignment = await session.scalar(
            select(Assignment).where(Assignment.order_id == order.id)
        )

    timeline: list[TimelineEventOut] = []
    if _detail_wants("timeline", includes):
        audit_rows = list(
            (
                await session.scalars(
                    select(AuditLog)
                    .where(AuditLog.entity == "order", AuditLog.entity_id == str(order.id))
                    .order_by(AuditLog.created_at)
                )
            ).all()
        )
        timeline = [
            TimelineEventOut(
                ts=row.created_at.replace(tzinfo=timezone.utc)
                if row.created_at.tzinfo is None
                else row.created_at,
                action=row.action,
                actor=row.actor,
                after=row.after,
            )
            for row in audit_rows
        ]

    chat: list[ChatMessageOut] = []
    if _detail_wants("chat", includes) and customer:
        conv = await session.scalar(
            select(Conversation).where(
                Conversation.restaurant_id == restaurant_id,
                Conversation.phone == customer.phone,
                Conversation.counterpart == "customer",
            )
        )
        if conv:
            msg_rows = list(
                (
                    await session.scalars(
                        select(Message)
                        .where(Message.conversation_id == conv.id)
                        .order_by(Message.ts)
                    )
                ).all()
            )
            from app.conversation.service import message_display_text

            chat = [
                ChatMessageOut(
                    direction=m.direction,
                    text=message_display_text(m.payload or {}),
                    ts=m.ts,
                )
                for m in msg_rows
            ]

    route: list[GpsPingOut] = []
    if _detail_wants("route", includes) and order.rider_id and assignment:
        upper = order.delivered_at or datetime.now(timezone.utc)
        ping_rows = list(
            (
                await session.scalars(
                    select(RiderLocation)
                    .where(
                        RiderLocation.rider_id == order.rider_id,
                        RiderLocation.restaurant_id == restaurant_id,
                        RiderLocation.ts >= assignment.assigned_at,
                        RiderLocation.ts <= upper,
                    )
                    .order_by(RiderLocation.ts)
                )
            ).all()
        )
        route = [
            GpsPingOut(latitude=p.latitude, longitude=p.longitude, ts=p.ts)
            for p in ping_rows
        ]

    # 9. Marketing opt-in flag
    opted_out = (
        await is_opted_out(session, restaurant_id=restaurant_id, phone=customer.phone)
        if customer
        else False
    )

    # Customer name + stats: fall back to a delivery receiver name when the
    # customer has none on file, and derive order stats live from the orders
    # table so the drawer is correct even if the denormalized columns are stale.
    stats = (await compute_customer_order_stats(session, [customer.id])).get(customer.id, {})
    customer_name = customer.name
    if not (customer_name or "").strip():
        # Use the customer's most recent receiver name across ALL their addresses
        # (this order may be a draft with no address yet, but they ordered before).
        customer_name = await session.scalar(
            select(CustomerAddress.receiver_name)
            .where(
                CustomerAddress.customer_id == customer.id,
                CustomerAddress.receiver_name.isnot(None),
            )
            .order_by(CustomerAddress.id.desc())
            .limit(1)
        )

    dispatch_explain: dict | None = None
    if _detail_wants("dispatch", includes) and assignment and assignment.algorithm_score:
        dispatch_explain = assignment.algorithm_score

    batch_preview_label: str | None = None
    if order.rider_id is None and order.status in ("confirmed", "preparing", "ready"):
        from app.dispatch.preview_cache import get_cached_preview

        cached = await get_cached_preview(restaurant_id)
        if cached is not None:
            batch_preview_label = cached.get(order.id)
        elif includes is None:
            from app.dispatch.service import preview_batch_groups

            batch_preview_label = (await preview_batch_groups(
                session, restaurant_id=restaurant_id
            )).get(order.id)

    return OrderDetailOut(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        items=items,
        address=address,
        customer=CustomerDetailOut(
            id=customer.id,
            name=customer_name,
            phone=customer.phone,
            total_orders=stats.get("total_orders", customer.total_orders),
            total_spend=stats.get("total_spend", customer.total_spend),
            first_order_at=stats.get("first_order_at") or customer.first_order_at,
            last_order_at=stats.get("last_order_at") or customer.last_order_at,
            marketing_opted_in=not opted_out,
        ),
        rider=rider,
        subtotal=order.subtotal,
        delivery_fee_aed=order.delivery_fee_aed,
        total=order.total,
        created_at=order.created_at,
        delivered_at=order.delivered_at,
        sla_deadline=order.sla_deadline,
        sla_started_at=order.sla_confirmed_at,
        prep_deadline=order.prep_deadline,
        cook_estimate_minutes=order.cook_estimate_minutes,
        timeline=timeline,
        chat=chat,
        convo_summary=(
            await _kitchen_convo_summary(
                items_rows,
                order_details=order.additional_details,
                delivery_details=address.additional_details if address else None,
                chat=_chat_for_this_order(chat, order) if chat else None,
            )
            if _detail_wants("chat", includes)
            else None
        ),
        route=route,
        batch_preview_label=batch_preview_label,
        dispatch_explain=dispatch_explain,
    )


async def patch_customer(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
    name: str | None,
    phone: str | None,
    marketing_opted_in: bool | None,
) -> Customer:
    """Update customer name/phone and/or marketing opt preference."""
    from sqlalchemy import select as sa_select
    from app.marketing.optout import record_opt_in, record_opt_out

    customer = await session.scalar(
        sa_select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant_id,
        )
    )
    if not customer:
        raise ValueError("Customer not found")

    # Capture phone BEFORE mutation so marketing opt targets the current phone
    effective_phone = customer.phone

    if name is not None:
        customer.name = name
    if phone is not None:
        customer.phone = phone
    if marketing_opted_in is True:
        await record_opt_in(session, restaurant_id=restaurant_id, phone=effective_phone)
    elif marketing_opted_in is False:
        await record_opt_out(
            session, restaurant_id=restaurant_id,
            phone=effective_phone, source="manager_dashboard",
        )

    await session.flush()
    return customer


async def patch_address(
    session: "AsyncSession",
    *,
    restaurant_id: int,
    customer_id: int,
    address_id: int,
    room_apartment: str | None,
    building: str | None,
    receiver_name: str | None,
    additional_details: str | None,
) -> CustomerAddress:
    """Update address fields. Raises ValueError if address not owned by customer."""
    from sqlalchemy import select as sa_select

    # Verify the customer belongs to this restaurant tenant, then check address
    # ownership. Both failures surface as "Address not found" so that callers
    # cannot enumerate customer IDs across tenants.
    customer = await session.scalar(
        sa_select(Customer).where(
            Customer.id == customer_id,
            Customer.restaurant_id == restaurant_id,
        )
    )

    addr = await session.scalar(
        sa_select(CustomerAddress).where(
            CustomerAddress.id == address_id,
            CustomerAddress.customer_id == customer_id,
        )
    ) if customer else None

    if not addr:
        raise ValueError("Address not found")

    if room_apartment is not None:
        addr.room_apartment = room_apartment
    if building is not None:
        addr.building = building
    if receiver_name is not None:
        addr.receiver_name = receiver_name
    if additional_details is not None:
        addr.additional_details = additional_details

    await session.flush()
    return addr
