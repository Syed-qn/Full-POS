"""Partner delivery status OUT to POS (Phase 4)."""
from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.models import CodCollection
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Restaurant, Rider
from app.ordering.models import Order
from app.ordering.payments import cod_due_aed
from app.partner.integration import partner_settings
from app.partner.webhooks.enqueue import enqueue_partner_webhook

_EVENT_BY_STATUS: dict[str, str] = {
    "assigned": "order.rider_assigned",
    "picked_up": "order.picked_up",
    "delivered": "order.delivered",
}

_LOCATION_RATE: dict[tuple[int, int], float] = {}
_LOCATION_MIN_INTERVAL_SEC = 10.0


async def _rider_block(session: AsyncSession, rider_id: int | None) -> dict | None:
    if rider_id is None:
        return None
    rider = await session.get(Rider, rider_id)
    if rider is None:
        return None
    return {"id": rider.id, "name": rider.name, "phone": rider.phone}


async def _batch_id_for_order(session: AsyncSession, order_id: int) -> int | None:
    return await session.scalar(
        select(BatchOrder.batch_id).where(BatchOrder.order_id == order_id)
    )


async def _eta_minutes(session: AsyncSession, order: Order) -> int | None:
    if order.promised_eta is not None:
        now = datetime.now(timezone.utc)
        eta = order.promised_eta
        if eta.tzinfo is None:
            eta = eta.replace(tzinfo=timezone.utc)
        return max(0, int((eta - now).total_seconds() / 60))
    batch_id = await _batch_id_for_order(session, order.id)
    if batch_id is not None:
        batch = await session.get(Batch, batch_id)
        if batch is not None and batch.total_est_min is not None:
            return batch.total_est_min
    return None


async def build_partner_delivery_data(
    session: AsyncSession,
    *,
    order: Order,
) -> dict:
    """Serialize delivery snapshot for POS poll + outbound webhooks."""
    restaurant = await session.get(Restaurant, order.restaurant_id)
    cfg = partner_settings(restaurant) if restaurant else {}

    cod_collected: float | None = None
    if order.status == "delivered":
        coll = await session.scalar(
            select(CodCollection).where(CodCollection.order_id == order.id)
        )
        cod_collected = (
            float(coll.amount_aed)
            if coll is not None
            else float(cod_due_aed(order))
        )

    batch_id = await _batch_id_for_order(session, order.id)
    rider = await _rider_block(session, order.rider_id)
    eta = await _eta_minutes(session, order)

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "pos_store_id": cfg.get("pos_store_id") or "",
        "pos_order_id": order.pos_order_id,
        "status": order.status,
        "rider": rider,
        "batch_id": batch_id,
        "eta_minutes": eta,
        "promised_eta": order.promised_eta.isoformat() if order.promised_eta else None,
        "delivered_at": order.delivered_at.isoformat() if order.delivered_at else None,
        "late": bool(order.late) if order.late is not None else False,
        "cod_due": float(cod_due_aed(order)),
        "cod_collected": cod_collected,
    }


async def notify_partner_delivery_event(
    session: AsyncSession,
    *,
    order: Order,
    event_type: str,
    extra: dict | None = None,
) -> int | None:
    """Enqueue a delivery lifecycle webhook when partner integration is enabled."""
    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is None:
        return None
    cfg = partner_settings(restaurant)
    if not cfg["partner_enabled"] or not cfg["partner_webhook_url"]:
        return None

    data = await build_partner_delivery_data(session, order=order)
    if extra:
        data.update(extra)

    suffix = event_type.removeprefix("order.").replace("_", "-")
    row = await enqueue_partner_webhook(
        session,
        restaurant=restaurant,
        event_type=event_type,
        data=data,
        idempotency_key=f"pos-order-{suffix}-{order.id}",
    )
    return row.id if row is not None else None


async def notify_partner_delivery_transition(
    session: AsyncSession,
    *,
    order: Order,
    to_status: str,
) -> int | None:
    """Map FSM status to a partner webhook event and enqueue."""
    event_type = _EVENT_BY_STATUS.get(to_status)
    if event_type is None:
        return None
    return await notify_partner_delivery_event(
        session, order=order, event_type=event_type
    )


async def get_partner_order_delivery(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    order_id: int,
) -> dict | None:
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant.id:
        return None
    return await build_partner_delivery_data(session, order=order)


async def get_partner_rider_location(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    rider_id: int,
) -> dict | None | bool:
    """Latest rider GPS ping (tenant-scoped).

    Returns False when rider not found for this restaurant; None when no ping yet.
    """
    from app.identity import service as identity_service

    key = (restaurant.id, rider_id)
    now = time.monotonic()
    last = _LOCATION_RATE.get(key, 0.0)
    if now - last < _LOCATION_MIN_INTERVAL_SEC:
        raise RateLimitError("Rate limit: one request per 10 seconds per rider")
    _LOCATION_RATE[key] = now

    result = await identity_service.latest_rider_location(
        session, restaurant_id=restaurant.id, rider_id=rider_id
    )
    if result is False:
        return False
    if result is None:
        return None
    return {
        "rider_id": rider_id,
        "latitude": result["lat"],
        "longitude": result["lng"],
        "updated_at": result["ts"].isoformat(),
    }


class RateLimitError(Exception):
    """Partner rider location polled too frequently."""