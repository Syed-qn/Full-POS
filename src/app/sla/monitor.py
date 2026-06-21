"""SLA monitor Celery task (spec §4.4, P4-T14).

Scans all open orders every 30s (spec §4.5 heartbeat). Fires idempotent SlaEvent rows at:
  yellow_30 (30 min) — customer + manager outbox alert
  red_35   (35 min) — manager alert only
  breach_40 (40 min) — manager alert + auto-coupon if NOT weather_delay_disclosed

Idempotency: uq_sla_events_order_type blocks duplicate rows; ON CONFLICT DO NOTHING.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from celery import shared_task
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import async_session_factory
from app.metrics import SLA_BREACHES
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, Order
from app.outbox.service import enqueue_message
from app.sla.models import SlaEvent
from app.whatsapp.port import OutboundMessageType

logger = logging.getLogger(__name__)

_ACTIVE_STATUSES = {
    str(OrderStatus.CONFIRMED),
    str(OrderStatus.PREPARING),
    str(OrderStatus.READY),
    str(OrderStatus.ASSIGNED),
    str(OrderStatus.PICKED_UP),
    str(OrderStatus.ARRIVING),
}

_THRESHOLDS = [
    ("yellow_30", 30),
    ("red_35", 35),
    ("breach_40", 40),
]


@shared_task(name="sla.monitor_tick", bind=True, max_retries=3, default_retry_delay=10)
def sla_monitor_tick(self) -> None:  # type: ignore[override]
    asyncio.run(_run_monitor())


async def _run_monitor() -> None:
    async with async_session_factory() as session:
        now = datetime.now(timezone.utc)
        open_orders = (
            await session.scalars(
                select(Order).where(Order.status.in_(list(_ACTIVE_STATUSES)))
            )
        ).all()
        for order in open_orders:
            if order.sla_confirmed_at is None:
                continue
            confirmed_at = order.sla_confirmed_at
            if confirmed_at.tzinfo is None:
                confirmed_at = confirmed_at.replace(tzinfo=timezone.utc)
            elapsed_min = (now - confirmed_at).total_seconds() / 60.0
            for event_type, threshold_min in _THRESHOLDS:
                if elapsed_min < threshold_min:
                    continue
                await _fire_event(session, order=order, event_type=event_type, now=now)

            pd = order.prep_deadline
            if pd is not None and pd.tzinfo is None:
                pd = pd.replace(tzinfo=timezone.utc)

            # "Start cooking by" = prep_deadline − cook estimate. While the order is still
            # only CONFIRMED (not started), warn once it's past the point where even the
            # slowest dish can't finish in time.
            if (
                order.status == str(OrderStatus.CONFIRMED)
                and pd is not None
                and order.cook_estimate_minutes is not None
            ):
                start_by = pd - timedelta(minutes=order.cook_estimate_minutes)
                if now >= start_by:
                    await _fire_kitchen_event(
                        session, order=order, now=now, event_type="start_late",
                        body=(
                            f"🔥 Start cooking {order.order_number} NOW — it won't be "
                            "ready in time for the 40-min SLA otherwise."
                        ),
                    )

            # Kitchen plate-by deadline: while the order is still cooking, warn the
            # manager the moment it passes its distance-driven prep_deadline so they can
            # push the kitchen before the drive budget is gone.
            if (
                order.status in (str(OrderStatus.CONFIRMED), str(OrderStatus.PREPARING))
                and pd is not None
                and now >= pd
            ):
                await _fire_kitchen_event(
                    session, order=order, now=now, event_type="prep_late",
                    body=(
                        f"👨‍🍳 Plate {order.order_number} NOW — it's past the kitchen "
                        "deadline and the delivery still needs time to make the 40-min SLA."
                    ),
                )
        await session.commit()


async def _fire_kitchen_event(
    session: AsyncSession, *, order: Order, now: datetime, event_type: str, body: str
) -> None:
    """Manager kitchen alert (start_late / prep_late). Idempotent via the
    uq_sla_events_order_type constraint (one row per order per type)."""
    stmt = (
        pg_insert(SlaEvent)
        .values(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            type=event_type,
            ts=now,
            notified={},
        )
        .on_conflict_do_nothing(constraint="uq_sla_events_order_type")
        .returning(SlaEvent.id)
    )
    if (await session.execute(stmt)).first() is None:
        return  # already fired

    from app.identity.models import Restaurant as RestaurantModel

    restaurant = await session.get(RestaurantModel, order.restaurant_id)
    if restaurant:
        await enqueue_message(
            session,
            restaurant_id=order.restaurant_id,
            to_phone=restaurant.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": body},
            idempotency_key=f"{event_type}-{order.id}",
        )


async def _fire_event(
    session: AsyncSession,
    *,
    order: Order,
    event_type: str,
    now: datetime,
) -> None:
    stmt = (
        pg_insert(SlaEvent)
        .values(
            order_id=order.id,
            restaurant_id=order.restaurant_id,
            type=event_type,
            ts=now,
            notified={},
        )
        .on_conflict_do_nothing(constraint="uq_sla_events_order_type")
        .returning(SlaEvent.id)
    )
    result = await session.execute(stmt)
    if result.first() is None:
        return  # already fired

    # Customer alert: yellow_30 and breach_40
    if event_type in ("yellow_30", "breach_40"):
        customer = await session.get(Customer, order.customer_id)
        if customer:
            msg = (
                f"Your order {order.order_number} is taking longer than expected. "
                "We're working on it — thank you for your patience!"
                if event_type == "yellow_30"
                else f"We're sorry your order {order.order_number} is delayed. "
                "A discount coupon will be applied to your next order."
            )
            await enqueue_message(
                session,
                restaurant_id=order.restaurant_id,
                to_phone=customer.phone,
                msg_type=OutboundMessageType.TEXT,
                payload={"body": msg},
                idempotency_key=f"sla-cust-{order.id}-{event_type}",
            )

    # Manager alert: all event types
    from app.identity.models import Restaurant as RestaurantModel
    restaurant = await session.get(RestaurantModel, order.restaurant_id)
    if restaurant:
        mgr_msg = {
            "yellow_30": f"⚠️ Order {order.order_number} hit 30-min mark.",
            "red_35": f"🔴 Order {order.order_number} at 35 min — escalate now!",
            "breach_40": f"🚨 SLA BREACHED: Order {order.order_number} exceeded 40 min.",
        }[event_type]
        await enqueue_message(
            session,
            restaurant_id=order.restaurant_id,
            to_phone=restaurant.phone,
            msg_type=OutboundMessageType.TEXT,
            payload={"body": mgr_msg},
            idempotency_key=f"sla-mgr-{order.id}-{event_type}",
        )

    # Prometheus metric: increment SLA breach counter
    if event_type == "breach_40":
        SLA_BREACHES.labels(restaurant_id=str(order.restaurant_id)).inc()

    # Auto-coupon at breach_40 if NOT weather-delay-disclosed
    if event_type == "breach_40" and not order.weather_delay_disclosed:
        from app.coupons.service import issue_coupon
        await issue_coupon(
            session,
            restaurant_id=order.restaurant_id,
            customer_id=order.customer_id,
            order_id=order.id,
            discount_aed=Decimal("10.00"),
        )
