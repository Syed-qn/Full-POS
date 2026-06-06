"""Live rider ETA for customer-facing status replies (spec §4.3 + §3).

Schema notes (no new migrations):
  * Rider position is the latest ``rider_locations`` ping for the rider;
    riders with no ping yield no ETA (graceful degradation).
  * Order drop-off coords are resolved via ``address_id`` -> CustomerAddress.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dispatch.models import BatchOrder, RiderLocation
from app.geo.port import GeoPort
from app.ordering.models import CustomerAddress, Order

_HUMAN_STATUS: dict[str, str] = {
    "draft": "We're still taking your order.",
    "pending_confirmation": "Waiting for your confirmation.",
    "confirmed": "Order confirmed — heading to the kitchen.",
    "preparing": "Your order is being prepared.",
    "ready": "Your order is ready and waiting for a rider.",
    "assigned": "A rider has been assigned to your order.",
    "picked_up": "Your rider has picked up your order.",
    "arriving": "Your rider is on the way!",
    "delivered": "Your order has been delivered. Enjoy!",
    "cancelled": "This order was cancelled.",
}

_EN_ROUTE = frozenset({"assigned", "picked_up", "arriving"})


async def _latest_rider_position(
    session: AsyncSession, rider_id: int
) -> tuple[float, float] | None:
    """Return (lat, lon) of the most recent RiderLocation ping, or None."""
    row = await session.scalar(
        select(RiderLocation)
        .where(RiderLocation.rider_id == rider_id)
        .order_by(RiderLocation.ts.desc())
        .limit(1)
    )
    if row is None:
        return None
    return (row.latitude, row.longitude)


async def _dropoff_coords(
    session: AsyncSession, order: Order
) -> tuple[float, float] | None:
    """Return (lat, lon) for the order's delivery address, or None."""
    if order.address_id is None:
        return None
    addr = await session.get(CustomerAddress, order.address_id)
    if addr is None or addr.latitude is None or addr.longitude is None:
        return None
    return (addr.latitude, addr.longitude)


async def build_tracking_reply(
    session: AsyncSession,
    *,
    order: Order,
    geo: GeoPort,
) -> str:
    """Human-readable status line, plus live rider ETA when en route.

    For ``assigned`` / ``picked_up`` / ``arriving`` statuses the function:
      1. Looks up the rider's most recent GPS ping from ``rider_locations``.
      2. Resolves the drop-off coords from ``customer_addresses``.
      3. Computes distance via the geo provider.
      4. Adds a 10-min buffer per preceding stop in the same batch.
      5. Appends " ETA ~N min[  (estimated)]." to the base status string.

    If rider position or drop-off coords are unavailable the base status
    string is returned without an ETA (graceful degradation).
    """
    status = str(order.status)
    base = _HUMAN_STATUS.get(status, "We're processing your order.")

    if status not in _EN_ROUTE or order.rider_id is None:
        return base

    rider_pos = await _latest_rider_position(session, order.rider_id)
    if rider_pos is None:
        return base

    dropoff = await _dropoff_coords(session, order)
    if dropoff is None:
        return base

    rider_lat, rider_lon = rider_pos
    drop_lat, drop_lon = dropoff

    dist = geo.distance_km(rider_lat, rider_lon, drop_lat, drop_lon)

    # Batch buffer: add 10 min per preceding stop so the customer at stop 2
    # isn't told "3 min" when the rider still has another delivery first.
    buffer = 0
    bo = await session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == order.id)
    )
    if bo is not None:
        siblings = (
            await session.scalars(
                select(BatchOrder).where(BatchOrder.batch_id == bo.batch_id)
            )
        ).all()
        if len(siblings) > 1:
            buffer = 10 * max(0, bo.sequence - 1)

    eta = geo.eta_minutes(dist, buffer_minutes=buffer)
    est = " (estimated)" if getattr(geo, "is_estimate", False) else ""
    return f"{base} ETA ~{eta} min{est}."
