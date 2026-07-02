"""Partner order pull/ack + payload builder (Phase 1)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.models import Restaurant
from app.ordering.fsm import OrderStatus
from app.ordering.models import Customer, CustomerAddress, Order, OrderItem
from app.partner.integration import partner_settings
from app.partner.webhooks.enqueue import enqueue_partner_webhook


async def build_partner_order_data(
    session: AsyncSession,
    *,
    order: Order,
    restaurant: Restaurant | None = None,
) -> dict:
    """Serialize an order for POS intake (webhook body ``data`` or poll response)."""
    if restaurant is None:
        restaurant = await session.get(Restaurant, order.restaurant_id)
    cfg = partner_settings(restaurant) if restaurant else {}
    customer = await session.get(Customer, order.customer_id)
    address: CustomerAddress | None = None
    if order.address_id is not None:
        address = await session.get(CustomerAddress, order.address_id)
    items = (
        await session.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ).all()

    from app.ordering.payments import cod_due_aed

    cod_due = cod_due_aed(order)
    addr_block: dict | None = None
    if address is not None:
        addr_block = {
            "room_apartment": address.room_apartment,
            "building": address.building,
            "receiver_name": address.receiver_name,
            "additional_details": address.additional_details,
            "latitude": address.latitude,
            "longitude": address.longitude,
        }

    return {
        "order_id": order.id,
        "order_number": order.order_number,
        "pos_store_id": cfg.get("pos_store_id") or "",
        "status": order.status,
        "pos_order_id": order.pos_order_id,
        "pos_push_status": order.pos_push_status,
        "customer": {
            "id": customer.id if customer else None,
            "name": customer.name if customer else None,
            "phone": customer.phone if customer else None,
        },
        "items": [
            {
                "dish_number": i.dish_number,
                "name": i.dish_name,
                "variant_name": i.variant_name,
                "qty": i.qty,
                "price": float(i.price_aed),
                "notes": i.notes,
            }
            for i in items
        ],
        "additional_details": order.additional_details,
        "address": addr_block,
        "subtotal": float(order.subtotal),
        "delivery_fee": float(order.delivery_fee_aed),
        "wallet_applied": float(order.wallet_applied_aed or 0),
        "total": float(order.total),
        "cod_due": float(cod_due),
        "payment": "COD",
        "distance_km": order.distance_km,
        "promised_eta": order.promised_eta.isoformat() if order.promised_eta else None,
        "sla_deadline": order.sla_deadline.isoformat() if order.sla_deadline else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


async def push_order_to_partner(
    session: AsyncSession,
    *,
    order: Order,
) -> int | None:
    """Enqueue ``order.created`` for POS when integration is enabled.

    Sets ``pos_push_status=pending`` on the order. Caller commits, then
    ``flush_pending_partner_webhooks`` to deliver. Returns delivery row id.
    """
    if order.status != "confirmed":
        return None
    restaurant = await session.get(Restaurant, order.restaurant_id)
    if restaurant is None:
        return None
    cfg = partner_settings(restaurant)
    if not cfg["partner_enabled"]:
        return None
    if not cfg["partner_webhook_url"] and cfg["pos_order_push_mode"] != "poll":
        return None
    if order.pos_push_status in ("pending", "acked"):
        return None

    order.pos_push_status = "pending"
    order.pos_pushed_at = datetime.now(timezone.utc)

    if not cfg["partner_webhook_url"]:
        # Poll-only: POS pulls GET /partner/orders — no outbound webhook row.
        await session.flush()
        return None

    data = await build_partner_order_data(session, order=order, restaurant=restaurant)
    row = await enqueue_partner_webhook(
        session,
        restaurant=restaurant,
        event_type="order.created",
        data=data,
        idempotency_key=f"pos-order-created-{order.id}",
    )
    if row is None:
        return None
    await session.flush()
    return row.id


async def list_partner_orders(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    status: str | None = None,
    since: datetime | None = None,
    unacked_only: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> list[Order]:
    """Poll endpoint: confirmed orders for POS, optionally only not yet acked."""
    page = max(1, min(limit, 500))
    stmt = select(Order).where(Order.restaurant_id == restaurant.id)
    if status is None:
        stmt = stmt.where(Order.status == "confirmed")
    elif status.lower() != "all":
        # "all" → no status filter (full order history); anything else filters exactly.
        stmt = stmt.where(Order.status == status)
    if since is not None:
        stmt = stmt.where(Order.created_at >= since)
    if unacked_only:
        stmt = stmt.where(
            (Order.pos_push_status.is_(None)) | (Order.pos_push_status != "acked")
        )
    return list(
        (
            await session.scalars(
                stmt.order_by(Order.created_at.asc(), Order.id.asc())
                .limit(page)
                .offset(max(0, offset))
            )
        ).all()
    )


async def ack_partner_order(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    order_id: int,
    pos_order_id: str,
) -> Order | None:
    """POS acknowledges receipt; stores their order id."""
    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant.id:
        return None
    order.pos_order_id = pos_order_id.strip()
    order.pos_push_status = "acked"
    await session.flush()
    return order


_KITCHEN_RANK: dict[OrderStatus, int] = {
    OrderStatus.CONFIRMED: 1,
    OrderStatus.PREPARING: 2,
    OrderStatus.READY: 3,
}


async def advance_kitchen_to(
    session: AsyncSession,
    *,
    order: Order,
    target: OrderStatus,
    actor: str = "pos",
) -> Order:
    """Advance through kitchen FSM until ``target`` (e.g. confirmed→ready in one call)."""
    from app.ordering.service import advance_kitchen_status

    current = OrderStatus(order.status)
    if current == target:
        return order
    cur_rank = _KITCHEN_RANK.get(current)
    tgt_rank = _KITCHEN_RANK.get(target)
    if cur_rank is not None and tgt_rank is not None and cur_rank > tgt_rank:
        raise ValueError(
            f"Cannot move order from '{order.status}' back to '{target}'."
        )
    if cur_rank is None:
        raise ValueError(
            f"Cannot advance kitchen status from '{order.status}'. "
            f"Only confirmed or preparing orders can be advanced."
        )

    while OrderStatus(order.status) != target:
        # Reaching READY triggers synchronous auto-dispatch, which overshoots the
        # order past READY to ASSIGNED. Stop once the kitchen FSM can no longer be
        # advanced — the target has been reached (and may already be dispatched).
        if OrderStatus(order.status) not in (OrderStatus.CONFIRMED, OrderStatus.PREPARING):
            break
        order = await advance_kitchen_status(session, order=order, actor=actor)
    return order


async def apply_partner_kitchen_status(
    session: AsyncSession,
    *,
    restaurant: Restaurant,
    order_id: int,
    pos_status: str,
    reason: str | None = None,
) -> Order:
    """Apply a POS kitchen status update — uses the same paths as the dashboard."""
    from app.ordering.fsm import IllegalTransitionError, OrderStatus
    from app.ordering.service import cancel_order
    from app.partner.status_map import parse_pos_kitchen_status

    order = await session.get(Order, order_id)
    if order is None or order.restaurant_id != restaurant.id:
        raise ValueError("Order not found")

    mapped = parse_pos_kitchen_status(pos_status)

    if mapped == "cancelled":
        try:
            await cancel_order(session, order=order, actor="pos", reason=reason)
        except IllegalTransitionError as exc:
            raise ValueError(
                f"Order in status '{order.status}' can no longer be cancelled."
            ) from exc
        await session.commit()
        await session.refresh(order)
        return order

    target = OrderStatus(mapped)
    if target == OrderStatus.CONFIRMED:
        # POS ack of receipt — order is already confirmed when they see it.
        if OrderStatus(order.status) in (
            OrderStatus.CONFIRMED,
            OrderStatus.PREPARING,
            OrderStatus.READY,
            OrderStatus.ASSIGNED,
            OrderStatus.PICKED_UP,
            OrderStatus.ARRIVING,
            OrderStatus.DELIVERED,
        ):
            return order
        raise ValueError(
            f"Cannot mark accepted from status '{order.status}'."
        )

    return await advance_kitchen_to(session, order=order, target=target, actor="pos")