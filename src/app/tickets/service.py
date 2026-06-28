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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.outbox.service import enqueue_message
from app.tickets.models import Ticket
from app.wallet import service as wallet_service
from app.whatsapp.port import OutboundMessageType


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
    session: AsyncSession, *, restaurant_id: int, status: str | None = None
) -> list[Ticket]:
    stmt = select(Ticket).where(Ticket.restaurant_id == restaurant_id)
    if status is not None:
        stmt = stmt.where(Ticket.status == status)
    # Open first, then newest.
    stmt = stmt.order_by(Ticket.status != "open", Ticket.id.desc())
    return list(await session.scalars(stmt))


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


async def _notify(session: AsyncSession, ticket: Ticket, body: str) -> None:
    phone = await _customer_phone(session, ticket.customer_id)
    if not phone:
        return
    await enqueue_message(
        session,
        restaurant_id=ticket.restaurant_id,
        to_phone=phone,
        msg_type=OutboundMessageType.TEXT,
        payload={"body": body},
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
    await _notify(session, ticket, note)
    return ticket
