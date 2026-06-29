"""Complaint ticket endpoints (manager JWT, tenant-scoped).

Managers list/inspect tickets and resolve them with one of three actions. The AI
never hits these — it only opens tickets via the conversation engine.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.tickets import service as ticket_service
from app.tickets.schemas import TicketOut, TicketResolveIn
from app.tickets.service import TicketError

router = APIRouter(prefix="/api/v1/tickets", tags=["tickets"])


@router.get("", response_model=list[TicketOut])
async def list_tickets(
    status: str | None = Query(default=None),
    phone: str | None = Query(default=None),
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[TicketOut]:
    rows = await ticket_service.list_tickets(
        session, restaurant_id=restaurant.id, status=status, phone=phone
    )
    out = []
    for ticket, cust_phone, cust_name in rows:
        item = TicketOut.model_validate(ticket)
        item.customer_phone = cust_phone
        item.customer_name = cust_name
        out.append(item)
    return out


@router.get("/{ticket_id}", response_model=TicketOut)
async def get_ticket(
    ticket_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> TicketOut:
    try:
        ticket = await ticket_service.get_ticket(
            session, restaurant_id=restaurant.id, ticket_id=ticket_id
        )
    except TicketError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return TicketOut.model_validate(ticket)


@router.post("/{ticket_id}/resolve", response_model=TicketOut)
async def resolve_ticket(
    ticket_id: int,
    body: TicketResolveIn,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> TicketOut:
    actor = f"mgr:{restaurant.id}"
    try:
        if body.action == "wallet_refund":
            if body.amount is None:
                raise HTTPException(status_code=400, detail="amount required for wallet_refund")
            ticket = await ticket_service.resolve_wallet_refund(
                session, restaurant_id=restaurant.id, ticket_id=ticket_id,
                amount=Decimal(body.amount), note=body.note, created_by=actor,
            )
        elif body.action == "create_replacement":
            ticket = await ticket_service.create_replacement_order(
                session, restaurant_id=restaurant.id, ticket_id=ticket_id,
                note=body.note, created_by=actor,
            )
        elif body.action == "replacement":
            if body.replacement_order_id is None:
                raise HTTPException(status_code=400, detail="replacement_order_id required")
            ticket = await ticket_service.resolve_replacement(
                session, restaurant_id=restaurant.id, ticket_id=ticket_id,
                replacement_order_id=body.replacement_order_id, note=body.note, created_by=actor,
            )
        else:
            ticket = await ticket_service.resolve_no_action(
                session, restaurant_id=restaurant.id, ticket_id=ticket_id,
                note=body.note, created_by=actor,
            )
    except TicketError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    await session.commit()
    return TicketOut.model_validate(ticket)
