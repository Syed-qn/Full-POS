from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.db import get_session
from app.identity.deps import current_restaurant
from app.tables.models import DiningTable
from app.tables.schemas import StatusIn, TableIn, TableOut, TransferIn
from app.tables.service import (
    InvalidTableTransitionError,
    TableNotFoundError,
    transfer_order,
    transition_status,
)

router = APIRouter(prefix="/api/v1/tables", tags=["tables"])


@router.post("", response_model=TableOut, status_code=status.HTTP_201_CREATED)
async def create_table(
    body: TableIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    table = DiningTable(restaurant_id=restaurant.id, **body.model_dump())
    session.add(table)
    await session.commit()
    await session.refresh(table)
    return table


@router.get("", response_model=list[TableOut])
async def list_tables(
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.scalars(
        select(DiningTable).where(DiningTable.restaurant_id == restaurant.id)
    )
    return list(rows)


@router.patch("/{table_id}/status", response_model=TableOut)
async def update_table_status(
    table_id: int,
    body: StatusIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    before_table = await session.get(DiningTable, table_id)
    before_status = before_table.status if before_table else None
    try:
        table = await transition_status(
            session, table_id=table_id, restaurant_id=restaurant.id, to_status=body.status
        )
    except TableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidTableTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await record_audit(
        session, actor="manager", entity="table", entity_id=str(table.id),
        action="status_change", restaurant_id=restaurant.id,
        before={"status": before_status}, after={"status": table.status},
    )
    await session.commit()
    await session.refresh(table)
    return table


@router.patch("/{table_id}/transfer-order")
async def transfer_order_to_table(
    table_id: int,
    body: TransferIn,
    restaurant=Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
):
    try:
        order = await transfer_order(
            session, order_id=body.order_id, restaurant_id=restaurant.id, to_table_id=table_id,
        )
    except TableNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await record_audit(
        session, actor="manager", entity="order", entity_id=str(order.id),
        action="table_transfer", restaurant_id=restaurant.id,
        before=None, after={"table_id": table_id},
    )
    await session.commit()
    return {"order_id": order.id, "table_id": order.table_id}
