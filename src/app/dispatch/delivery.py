"""Delivery FSM (spec §3): assigned -> picked_up -> arriving -> delivered.

Every transition records an audit row in the caller's transaction (caller
commits). Illegal transitions raise ``InvalidTransitionError``.

On ``delivered``: the order's ``delivered_at`` is stamped, ``late`` is computed
against ``sla_deadline``, the order's ``BatchOrder.delivered_at`` is stamped, and
once every order in the batch is delivered the batch is marked ``completed`` and
its rider is freed (``status = "available"``) so the dispatch engine can pick
them up again on its next run.
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.dispatch.models import Batch, BatchOrder
from app.identity.models import Rider
from app.ordering.models import Order

# Legal forward transitions only (spec §3 — exact strings, never invent).
_DELIVERY_FSM: dict[str, set[str]] = {
    "assigned": {"picked_up"},
    "picked_up": {"arriving"},
    "arriving": {"delivered"},
}


class InvalidTransitionError(ValueError):
    """Raised on a delivery status transition not permitted by the FSM."""


async def advance_delivery(
    session: AsyncSession, *, order_id: int, to_status: str
) -> Order:
    """Move an order along the delivery FSM with audit + side effects."""
    order = await session.get(Order, order_id)
    if order is None:
        raise InvalidTransitionError(f"order {order_id} not found")

    allowed = _DELIVERY_FSM.get(order.status, set())
    if to_status not in allowed:
        raise InvalidTransitionError(
            f"cannot move order {order_id} from {order.status} to {to_status}"
        )

    before = {"status": order.status}
    now = datetime.now(timezone.utc)
    order.status = to_status

    if to_status == "delivered":
        order.delivered_at = now
        if order.sla_deadline is not None:
            order.late = now > order.sla_deadline
        await _complete_batch_order(session, order, now)
        from app.dispatch.tracking_live import TRACKING_EXPIRED, stop_tracking_session

        await stop_tracking_session(session, order_id=order.id, reason=TRACKING_EXPIRED)

        # Settle any wallet credit held against this order (no-op if none).
        from app.ordering.payments import capture_on_deliver

        await capture_on_deliver(session, order=order)

    await record_audit(
        session,
        actor="rider",
        restaurant_id=order.restaurant_id,
        entity="order",
        entity_id=str(order.id),
        action="state_transition",
        before=before,
        after={"status": to_status},
    )
    # Delivery bypasses fsm.transition, so refresh the customer's denormalized
    # stats here too — total_spend only moves once an order is delivered.
    from app.ordering.service import recompute_customer_stats

    await recompute_customer_stats(session, order.customer_id)

    # Loyalty (config-driven; no-op when settings.loyalty.enabled is False). Runs
    # AFTER stats refresh so tier/earn see the new totals. Best-effort — a loyalty
    # hiccup must never fail the delivery.
    if to_status == "delivered":
        try:
            from app.identity.models import Restaurant
            from app.loyalty import service as loyalty
            from app.ordering.models import Customer

            restaurant = await session.get(Restaurant, order.restaurant_id)
            customer = await session.get(Customer, order.customer_id)
            if restaurant is not None and customer is not None:
                settings = restaurant.settings or {}
                await loyalty.earn(session, order=order, settings=settings)
                await loyalty.recompute_tier(session, customer=customer, settings=settings)
                await loyalty.maybe_issue_recurring_reward(session, customer=customer, settings=settings)
        except Exception:  # noqa: BLE001 — loyalty never blocks delivery
            pass
    return order


async def _complete_batch_order(
    session: AsyncSession, order: Order, now: datetime
) -> None:
    """Stamp BatchOrder.delivered_at; if the batch is fully delivered, free the rider."""
    bo = await session.scalar(
        select(BatchOrder).where(BatchOrder.order_id == order.id)
    )
    if bo is None:
        return
    bo.delivered_at = now
    siblings = (
        await session.scalars(
            select(BatchOrder).where(BatchOrder.batch_id == bo.batch_id)
        )
    ).all()
    if all(s.delivered_at is not None for s in siblings):
        batch = await session.get(Batch, bo.batch_id)
        if batch is not None:
            batch.status = "completed"
            rider = await session.get(Rider, batch.rider_id)
            if rider is not None:
                rider.status = "available"
