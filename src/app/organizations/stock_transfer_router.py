"""Branch-facing stock transfer endpoints.

These sit apart from the HQ routes in ``organizations/router.py`` on purpose.
Those take ``current_organization``, which by its own docstring denies a branch
manager — correct for franchise administration, wrong for moving a crate of
chicken between two stores, which is ordinary floor work.

These take ``current_restaurant`` instead: the owner token OR a manager PIN
session. The branch is always read from the TOKEN, never from the request body,
so a manager can only ever send FROM their own store and receive INTO it.
"""
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.organizations.stock_transfer_branch import (
    cancel_stock_transfer,
    dispatch_stock_transfer,
    list_branch_transfers,
    list_sibling_branches,
    receive_stock_transfer,
)
from app.realtime.hooks import queue_event

router = APIRouter(prefix="/api/v1/branch-transfers", tags=["organizations"])


class TransferLineIn(BaseModel):
    ingredient_name: str
    quantity: Decimal
    unit: str | None = None


class DispatchIn(BaseModel):
    to_restaurant_id: int
    lines: list[TransferLineIn]
    note: str | None = None


class ReceivedLineIn(BaseModel):
    ingredient_name: str
    qty_received: Decimal


class ReceiveIn(BaseModel):
    # Empty means "everything arrived as sent", which is the ordinary case.
    lines: list[ReceivedLineIn] = []


@router.get("")
async def list_transfers(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    return await list_branch_transfers(session, restaurant_id=restaurant.id)


@router.get("/branches")
async def sibling_branches(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Where this branch may send stock. Empty for a single-site restaurant,
    which is what the dashboard uses to decide whether to show Transfers."""
    return await list_sibling_branches(session, restaurant_id=restaurant.id)


@router.post("", status_code=status.HTTP_201_CREATED)
async def dispatch(
    body: DispatchIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Send stock to a sibling branch. Deducts from this branch immediately."""
    try:
        transfer = await dispatch_stock_transfer(
            session,
            from_restaurant_id=restaurant.id,
            to_restaurant_id=body.to_restaurant_id,
            lines=[line.model_dump() for line in body.lines],
            dispatched_by="manager",
            note=body.note,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    # Both branches change: one loses stock now, the other gains a delivery to
    # accept. Announcing only our own would leave the other till stale.
    queue_event(session, restaurant.id, "inventory")
    queue_event(session, body.to_restaurant_id, "inventory")
    await session.commit()
    return {"id": transfer.id, "status": transfer.status}


@router.post("/{transfer_id}/receive")
async def receive(
    transfer_id: int,
    body: ReceiveIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Confirm what actually arrived. Only the destination branch may call it."""
    try:
        transfer = await receive_stock_transfer(
            session,
            transfer_id=transfer_id,
            to_restaurant_id=restaurant.id,
            received_by="manager",
            received={line.ingredient_name: line.qty_received for line in body.lines}
            or None,
        )
    except ValueError as exc:
        # 404 for "not yours": a 403 would confirm the transfer exists in
        # another organization, same reasoning as the KDS ownership checks.
        if "only the destination branch" in str(exc) or "not found" in str(exc):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "stock transfer not found") from exc
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    queue_event(session, restaurant.id, "inventory")
    queue_event(session, transfer.from_restaurant_id, "inventory")
    await session.commit()
    return {"id": transfer.id, "status": transfer.status}


@router.post("/{transfer_id}/cancel")
async def cancel(
    transfer_id: int,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    """Call a dispatch back before it is accepted. Returns the stock here."""
    try:
        transfer = await cancel_stock_transfer(
            session, transfer_id=transfer_id, from_restaurant_id=restaurant.id
        )
    except ValueError as exc:
        if "only the sending branch" in str(exc) or "not found" in str(exc):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "stock transfer not found") from exc
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    queue_event(session, restaurant.id, "inventory")
    queue_event(session, transfer.to_restaurant_id, "inventory")
    await session.commit()
    return {"id": transfer.id, "status": transfer.status}
