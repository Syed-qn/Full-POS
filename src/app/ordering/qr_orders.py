"""QR-table and tableside order helpers."""

from __future__ import annotations

import secrets
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.ordering.models import Order
from app.ordering.order_types import ORDER_TYPE_QR, ORDER_TYPE_TABLESIDE
from app.ordering.pos_orders import create_pos_order
from app.tables.models import DiningTable


async def ensure_table_qr_token(
    session: AsyncSession,
    *,
    restaurant_id: int,
    table_id: int,
) -> DiningTable:
    """Mint a stable QR token for the table if missing; return the table."""
    table = await session.get(DiningTable, table_id)
    if table is None or table.restaurant_id != restaurant_id:
        raise ValueError("table not found")
    if not table.qr_token:
        # 32 hex chars; unique constraint may theoretically collide — retry.
        for _ in range(5):
            token = secrets.token_hex(16)
            clash = await session.scalar(
                select(DiningTable.id).where(DiningTable.qr_token == token)
            )
            if clash is None:
                table.qr_token = token
                break
        else:
            raise RuntimeError("could not allocate qr_token")
        await record_audit(
            session,
            restaurant_id=restaurant_id,
            actor="manager",
            entity="table",
            entity_id=str(table.id),
            action="qr_token_issued",
            after={"qr_token": table.qr_token},
        )
        await session.flush()
    return table


async def get_table_by_qr_token(session: AsyncSession, *, qr_token: str) -> DiningTable | None:
    return await session.scalar(
        select(DiningTable).where(DiningTable.qr_token == qr_token)
    )


async def create_qr_order(
    session: AsyncSession,
    *,
    qr_token: str,
    customer_phone: str,
    customer_name: str | None,
    items: list[dict],
) -> Order:
    """Public QR path: place a dine-in QR order against the table token."""
    table = await get_table_by_qr_token(session, qr_token=qr_token)
    if table is None:
        raise ValueError("invalid QR token")
    return await create_pos_order(
        session,
        restaurant_id=table.restaurant_id,
        order_type=ORDER_TYPE_QR,
        customer_phone=customer_phone,
        customer_name=customer_name,
        items=items,
        table_id=table.id,
        delivery_fee_aed=Decimal("0.00"),
        auto_confirm=True,
    )


async def create_tableside_order(
    session: AsyncSession,
    *,
    restaurant_id: int,
    table_id: int,
    staff_id: int | None,
    customer_phone: str,
    customer_name: str | None,
    items: list[dict],
) -> Order:
    """Waiter tableside order for a seated table."""
    return await create_pos_order(
        session,
        restaurant_id=restaurant_id,
        order_type=ORDER_TYPE_TABLESIDE,
        customer_phone=customer_phone,
        customer_name=customer_name,
        items=items,
        table_id=table_id,
        staff_id=staff_id,
        delivery_fee_aed=Decimal("0.00"),
        auto_confirm=True,
    )
