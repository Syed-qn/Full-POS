from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.ordering.models import Order


class OrderStatus(StrEnum):
    DRAFT = "draft"
    PENDING_CONFIRMATION = "pending_confirmation"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    ARRIVING = "arriving"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    UNDELIVERABLE = "undeliverable"
    ON_RESALE = "on_resale"
    RESOLD = "resold"
    WRITTEN_OFF = "written_off"


class IllegalTransitionError(Exception):
    """Raised when a state transition is not permitted by the FSM."""


class OrderFSM:
    # Explicit adjacency map — every status present as a key.
    TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
        OrderStatus.DRAFT: {
            OrderStatus.PENDING_CONFIRMATION,
            OrderStatus.CANCELLED,
        },
        OrderStatus.PENDING_CONFIRMATION: {
            OrderStatus.CONFIRMED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.CONFIRMED: {
            OrderStatus.PREPARING,
            OrderStatus.CANCELLED,
        },
        OrderStatus.PREPARING: {
            OrderStatus.READY,
            # post-cooking cancellation: customer-cancel → on_resale (re-sell the cooked
            # food); restaurant-cancel → cancelled (food unavailable/unfit). The service
            # layer picks the edge by actor; the FSM permits both.
            OrderStatus.ON_RESALE,
            OrderStatus.CANCELLED,
        },
        OrderStatus.READY: {
            OrderStatus.ASSIGNED,
        },
        OrderStatus.ASSIGNED: {
            OrderStatus.PICKED_UP,
        },
        OrderStatus.PICKED_UP: {
            OrderStatus.ARRIVING,
            OrderStatus.UNDELIVERABLE,
        },
        OrderStatus.ARRIVING: {
            OrderStatus.DELIVERED,
            OrderStatus.UNDELIVERABLE,
        },
        OrderStatus.DELIVERED: set(),
        OrderStatus.CANCELLED: set(),
        OrderStatus.UNDELIVERABLE: set(),
        OrderStatus.ON_RESALE: {
            OrderStatus.RESOLD,
            OrderStatus.WRITTEN_OFF,
        },
        OrderStatus.RESOLD: set(),
        OrderStatus.WRITTEN_OFF: set(),
    }

    @classmethod
    def next_states(cls, current: OrderStatus) -> set[OrderStatus]:
        return cls.TRANSITIONS.get(current, set())

    @classmethod
    def validate(cls, current: OrderStatus, new: OrderStatus) -> None:
        """Raise IllegalTransitionError if the transition is not in the map."""
        allowed = cls.TRANSITIONS.get(current, set())
        if new not in allowed:
            raise IllegalTransitionError(
                f"Cannot transition order from {current!r} to {new!r}. "
                f"Allowed: {sorted(s.value for s in allowed)}"
            )


async def transition(
    session: AsyncSession,
    order: Order,
    new_status: OrderStatus,
    actor: str,
    extra_audit: dict | None = None,
) -> None:
    """Validate, apply, and audit a single order status transition.

    The caller MUST commit the session after this returns.

    Concurrency: validate() checks the in-memory order.status — two concurrent
    transitions on the same order can both pass and last-write-wins. Callers
    mutating from parallel workers MUST load the row with
    SELECT ... FOR UPDATE (session.get(Order, id, with_for_update=True)).
    """
    from app.audit.service import record_audit

    OrderFSM.validate(order.status, new_status)  # raises on illegal
    before = order.status
    order.status = new_status
    await record_audit(
        session,
        actor=actor,
        restaurant_id=order.restaurant_id,
        entity="order",
        entity_id=str(order.id),
        action="order_status_transition",
        before={"status": str(before), **(extra_audit or {})},
        after={"status": str(new_status)},
    )
    # Keep the customer's denormalized order stats (used by marketing segments)
    # in sync. Local import avoids a service<->fsm import cycle.
    from app.ordering.service import recompute_customer_stats

    await recompute_customer_stats(session, order.customer_id)
