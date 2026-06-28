"""Wallet read endpoints (manager JWT, tenant-scoped).

Balance/history are read-only here — credits originate from the ticket system
(refund-to-wallet) and order flow, never a direct write endpoint.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.identity.deps import current_restaurant
from app.identity.models import Restaurant
from app.ordering.models import Customer
from app.wallet import service as wallet_service
from app.wallet.models import WalletAccount, WalletEntry
from app.wallet.schemas import WalletBalanceOut, WalletEntryOut

router = APIRouter(prefix="/api/v1/wallet", tags=["wallet"])


async def _tenant_customer(session: AsyncSession, restaurant_id: int, customer_id: int) -> Customer:
    cust = await session.scalar(
        select(Customer).where(
            Customer.id == customer_id, Customer.restaurant_id == restaurant_id
        )
    )
    if cust is None:
        raise HTTPException(status_code=404, detail="customer not found")
    return cust


@router.get("/{customer_id}", response_model=WalletBalanceOut)
async def get_wallet(
    customer_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> WalletBalanceOut:
    await _tenant_customer(session, restaurant.id, customer_id)
    acc = await wallet_service.get_or_create_account(
        session, restaurant_id=restaurant.id, customer_id=customer_id
    )
    return WalletBalanceOut(
        customer_id=customer_id,
        balance_aed=await wallet_service.balance(session, account_id=acc.id),
        available_aed=await wallet_service.available(session, account_id=acc.id),
        status=acc.status,
    )


@router.get("/{customer_id}/entries", response_model=list[WalletEntryOut])
async def get_wallet_entries(
    customer_id: int,
    restaurant: Restaurant = Depends(current_restaurant),
    session: AsyncSession = Depends(get_session),
) -> list[WalletEntryOut]:
    await _tenant_customer(session, restaurant.id, customer_id)
    acc = await session.scalar(
        select(WalletAccount).where(
            WalletAccount.restaurant_id == restaurant.id,
            WalletAccount.customer_id == customer_id,
        )
    )
    if acc is None:
        return []
    rows = await session.scalars(
        select(WalletEntry)
        .where(WalletEntry.account_id == acc.id)
        .order_by(WalletEntry.id.desc())
    )
    return [WalletEntryOut.model_validate(r) for r in rows]
