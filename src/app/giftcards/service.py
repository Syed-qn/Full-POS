from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ordering.models import Customer
from app.wallet.service import balance, credit, get_or_create_account


async def purchase_gift_card(
    session: AsyncSession, *, restaurant_id: int, recipient_phone: str,
    amount_aed: Decimal, purchase_reference: str, created_by: str,
):
    from app.ordering.service import get_or_create_customer

    customer = await get_or_create_customer(session, restaurant_id=restaurant_id, phone=recipient_phone)
    return await credit(
        session, restaurant_id=restaurant_id, customer_id=customer.id, amount=amount_aed,
        idempotency_key=f"giftcard:{purchase_reference}", type="promo_credit",
        reason_note="gift card purchase", created_by=created_by,
    )


async def get_balance(session: AsyncSession, *, restaurant_id: int, phone: str) -> Decimal:
    customer = await session.scalar(
        select(Customer).where(Customer.restaurant_id == restaurant_id, Customer.phone == phone)
    )
    if customer is None:
        return Decimal("0.00")
    account = await get_or_create_account(session, restaurant_id=restaurant_id, customer_id=customer.id)
    return await balance(session, account_id=account.id)
