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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.service import record_collection
from app.dispatch.delivery import advance_delivery
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Rider
from app.ordering.models import CustomerAddress, Order
from app.outbox.service import enqueue_message
from app.whatsapp.port import OutboundMessageType


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


async def _send_stop(
    session: AsyncSession, restaurant_id: int, rider_phone: str, order: Order
) -> None:
    """Send the rider the next stop: nav link + Delivered button (COD-aware)."""
    coords = await _dropoff_coords(session, order)
    nav = f"\nNavigate: {_maps_link(*coords)}" if coords else ""
    # COD-only platform: every delivery collects cash.
    title = "Collect money & delivered" if order.total else "Delivered"
    await enqueue_message(
        session,
        restaurant_id=restaurant_id,
        to_phone=rider_phone,
        msg_type=OutboundMessageType.BUTTONS,
        payload={
            "body": f"Next stop: Order {order.order_number}{nav}",
            "buttons": [{"id": f"delivered:{order.id}", "title": title}],
        },
        idempotency_key=f"stop-{order.id}",
    )


async def handle_orders_picked(
    session: AsyncSession, *, restaurant_id: int, rider: Rider, batch_id: int
) -> None:
    """Rider pressed "Orders Picked": advance the whole batch and send stop #1."""
    batch = await session.get(Batch, batch_id)
    if batch is None or batch.rider_id != rider.id:
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
        if first_order is None:
            first_order = order
    if first_order is not None:
        await _send_stop(session, restaurant_id, rider.phone, first_order)


async def handle_delivered(
    session: AsyncSession, *, restaurant_id: int, rider: Rider, order_id: int
) -> None:
    """Rider pressed "Delivered": finish this order + record COD + send next stop."""
    order = await session.get(Order, order_id)
    if order is None or order.rider_id != rider.id:
        return
    # Collapse the geofence "arriving" step on the rider's physical confirmation.
    if order.status == "picked_up":
        await advance_delivery(session, order_id=order.id, to_status="arriving")
    await advance_delivery(session, order_id=order.id, to_status="delivered")
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
