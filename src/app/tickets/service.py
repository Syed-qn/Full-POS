"""Ticket service — complaint capture + the three manager resolution actions.

The AI may call :func:`create_ticket` (open + acknowledge) but NEVER resolves.
Resolution is always a manager action and always:
  * sets status -> resolved + resolution_action + resolved_at,
  * writes an audit row,
  * notifies the customer via the outbox (idempotent).
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.tickets.models import Ticket
from app.wallet import service as wallet_service


class TicketError(Exception):
    """Raised on invalid ticket operations (unknown, already resolved, bad input)."""


async def _customer_phone(session: AsyncSession, customer_id: int) -> str | None:
    from app.ordering.models import Customer

    cust = await session.get(Customer, customer_id)
    return cust.phone if cust else None


async def create_ticket(
    session: AsyncSession,
    *,
    restaurant_id: int,
    customer_id: int,
    order_id: int | None,
    source_message: str | None,
    evidence: list | None = None,
    category: str | None = None,
) -> Ticket:
    """Open a complaint ticket. Audited. Caller commits."""
    ticket = Ticket(
        restaurant_id=restaurant_id,
        customer_id=customer_id,
        order_id=order_id,
        source_message=source_message,
        evidence=evidence or [],
        category=category,
        status="open",
    )
    session.add(ticket)
    await session.flush()
    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="ticket",
        entity_id=str(ticket.id),
        action="opened",
        before=None,
        after={"order_id": order_id, "category": category},
    )
    return ticket


async def list_tickets(
    session: AsyncSession,
    *,
    restaurant_id: int,
    status: str | None = None,
    phone: str | None = None,
) -> list[tuple[Ticket, str | None, str | None]]:
    """Return (ticket, customer_phone, customer_name) rows, open first then newest.

    ``phone`` filters to tickets whose customer's phone contains the query.
    """
    from app.ordering.models import Customer

    stmt = (
        select(Ticket, Customer.phone, Customer.name)
        .join(Customer, Ticket.customer_id == Customer.id)
        .where(Ticket.restaurant_id == restaurant_id)
    )
    if status is not None:
        stmt = stmt.where(Ticket.status == status)
    if phone:
        stmt = stmt.where(Customer.phone.ilike(f"%{phone.strip()}%"))
    stmt = stmt.order_by(Ticket.status != "open", Ticket.id.desc())
    rows = await session.execute(stmt)
    return [(t, ph, nm) for t, ph, nm in rows.all()]


async def get_ticket(
    session: AsyncSession, *, restaurant_id: int, ticket_id: int
) -> Ticket:
    ticket = await session.scalar(
        select(Ticket).where(
            Ticket.id == ticket_id, Ticket.restaurant_id == restaurant_id
        )
    )
    if ticket is None:
        raise TicketError(f"ticket {ticket_id} not found")
    return ticket


def _ensure_open(ticket: Ticket) -> None:
    if ticket.status == "resolved":
        raise TicketError(f"ticket {ticket.id} already resolved")


async def _notify(session: AsyncSession, ticket: Ticket, body: str, summary: str) -> None:
    """Window-aware customer notification: session text inside 24h, else the
    approved ``ticket_resolution`` utility template."""
    from app.identity.models import Restaurant
    from app.whatsapp.templates import notify_customer

    phone = await _customer_phone(session, ticket.customer_id)
    if not phone:
        return
    restaurant = await session.get(Restaurant, ticket.restaurant_id)
    rname = restaurant.name if restaurant else "the restaurant"
    await notify_customer(
        session,
        restaurant_id=ticket.restaurant_id,
        phone=phone,
        session_text=body,
        template_key="ticket_resolution",
        variables=[rname, summary],
        idempotency_key=f"ticket:{ticket.id}:notify",
    )


async def resolve_wallet_refund(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ticket_id: int,
    amount: Decimal,
    note: str,
    created_by: str,
) -> Ticket:
    """Credit the customer's wallet and resolve. Idempotent on the ticket."""
    ticket = await get_ticket(session, restaurant_id=restaurant_id, ticket_id=ticket_id)
    if ticket.status == "resolved":
        return ticket
    if amount <= Decimal("0.00"):
        raise TicketError("refund amount must be positive")
    if not note or not note.strip():
        raise TicketError("resolution note is required")
    await wallet_service.credit(
        session,
        restaurant_id=restaurant_id,
        customer_id=ticket.customer_id,
        amount=amount,
        idempotency_key=f"ticket:{ticket_id}:refund",
        type="refund_credit",
        ticket_id=ticket_id,
        reason_note=note,
        created_by=created_by,
    )
    ticket.status = "resolved"
    ticket.resolution_action = "wallet_refund"
    ticket.resolution_amount_aed = amount.quantize(Decimal("0.01"))
    ticket.resolution_note = note
    ticket.assigned_to = created_by
    ticket.resolved_at = datetime.now(timezone.utc)
    # Refund-velocity guard: auto-freeze the wallet if the customer is over caps.
    from app.wallet.abuse import check_and_flag

    await check_and_flag(
        session, restaurant_id=restaurant_id, customer_id=ticket.customer_id,
        created_by=created_by,
    )
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="ticket",
        entity_id=str(ticket_id),
        action="resolved_wallet_refund",
        before={"status": "open"},
        after={"amount_aed": str(amount), "note": note},
    )
    await _notify(
        session, ticket,
        f"We're sorry about your experience. AED {amount} has been added to your "
        f"wallet as credit for your next order. 🙏",
        f"AED {amount} wallet credit added as an apology.",
    )
    return ticket


async def resolve_replacement(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ticket_id: int,
    replacement_order_id: int,
    note: str,
    created_by: str,
) -> Ticket:
    """Link a replacement order and resolve. Idempotent on the ticket."""
    ticket = await get_ticket(session, restaurant_id=restaurant_id, ticket_id=ticket_id)
    if ticket.status == "resolved":
        return ticket
    if not note or not note.strip():
        raise TicketError("resolution note is required")
    ticket.status = "resolved"
    ticket.resolution_action = "replacement"
    ticket.replacement_order_id = replacement_order_id
    ticket.resolution_note = note
    ticket.assigned_to = created_by
    ticket.resolved_at = datetime.now(timezone.utc)
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="ticket",
        entity_id=str(ticket_id),
        action="resolved_replacement",
        before={"status": "open"},
        after={"replacement_order_id": replacement_order_id, "note": note},
    )
    await _notify(
        session, ticket,
        "We're sorry about your experience. A replacement for your order is on the way. 🛵",
        "A replacement for your order is on the way.",
    )
    return ticket


async def create_replacement_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ticket_id: int,
    note: str,
    created_by: str,
) -> Ticket:
    """Create a REAL free replacement order from the complained-about order, then
    resolve the ticket. The new order is a normal order — it goes to the kitchen,
    is dispatchable to a rider, and is trackable — but is free to the customer
    (total 0, COD due 0). Idempotent on the ticket.
    """
    from decimal import Decimal

    from app.ordering.models import Order, OrderItem
    from app.ordering.service import finalize_confirmation

    ticket = await get_ticket(session, restaurant_id=restaurant_id, ticket_id=ticket_id)
    if ticket.status == "resolved":
        return ticket
    if not note or not note.strip():
        raise TicketError("resolution note is required")
    if ticket.order_id is None:
        raise TicketError(
            "this complaint isn't linked to an order — issue a refund or place a "
            "manual order instead"
        )
    original = await session.get(Order, ticket.order_id)
    if original is None:
        raise TicketError("original order not found")

    # New free order cloned from the original.
    count = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.restaurant_id == restaurant_id)
    ) or 0
    replacement = Order(
        restaurant_id=restaurant_id,
        customer_id=original.customer_id,
        order_number=f"{original.order_number}-R{count + 1:04d}",
        status="pending_confirmation",
        priority="normal",
        address_id=original.address_id,
        distance_km=original.distance_km,
        subtotal=original.subtotal,
        delivery_fee_aed=Decimal("0.00"),
        total=Decimal("0.00"),  # free replacement — customer pays nothing
        additional_details=f"Free replacement for {original.order_number} (ticket #{ticket.id})",
    )
    session.add(replacement)
    await session.flush()

    # Clone the line items so the kitchen knows what to make.
    items = (
        await session.scalars(
            select(OrderItem).where(OrderItem.order_id == original.id)
        )
    ).all()
    for it in items:
        session.add(
            OrderItem(
                order_id=replacement.id,
                dish_id=it.dish_id,
                dish_number=it.dish_number,
                dish_name=it.dish_name,
                variant_name=it.variant_name,
                price_aed=it.price_aed,
                qty=it.qty,
                notes=it.notes,
            )
        )
    await session.flush()

    # Run it through confirmation → starts the SLA clock, computes the prep
    # deadline, and enters the kitchen/dispatch/tracking pipeline like any order.
    await finalize_confirmation(session, order=replacement, actor=created_by)

    ticket.status = "resolved"
    ticket.resolution_action = "replacement"
    ticket.replacement_order_id = replacement.id
    ticket.resolution_note = note
    ticket.assigned_to = created_by
    ticket.resolved_at = datetime.now(timezone.utc)
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="ticket",
        entity_id=str(ticket_id),
        action="resolved_replacement_created",
        before={"status": "open"},
        after={"replacement_order_id": replacement.id, "note": note},
    )
    await _notify(
        session, ticket,
        f"We're sorry about your experience. A free replacement (order "
        f"{replacement.order_number}) is being prepared and is on its way. 🛵",
        f"A free replacement (order {replacement.order_number}) is on its way.",
    )
    return ticket


async def resolve_no_action(
    session: AsyncSession,
    *,
    restaurant_id: int,
    ticket_id: int,
    note: str,
    created_by: str,
) -> Ticket:
    """Close with no compensation. Requires a note. Idempotent on the ticket."""
    ticket = await get_ticket(session, restaurant_id=restaurant_id, ticket_id=ticket_id)
    if ticket.status == "resolved":
        return ticket
    if not note or not note.strip():
        raise TicketError("resolution note is required")
    ticket.status = "resolved"
    ticket.resolution_action = "resolved_no_action"
    ticket.resolution_note = note
    ticket.assigned_to = created_by
    ticket.resolved_at = datetime.now(timezone.utc)
    await record_audit(
        session,
        actor=created_by,
        restaurant_id=restaurant_id,
        entity="ticket",
        entity_id=str(ticket_id),
        action="resolved_no_action",
        before={"status": "open"},
        after={"note": note},
    )
    await _notify(session, ticket, note, note)
    return ticket
