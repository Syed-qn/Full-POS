from decimal import Decimal

import pytest

from app.giftcards.service import get_balance, purchase_gift_card


@pytest.mark.anyio
async def test_purchase_credits_new_customer_wallet(db_session, restaurant):
    await purchase_gift_card(
        db_session, restaurant_id=restaurant.id, recipient_phone="+971500000001",
        amount_aed=Decimal("100.00"), purchase_reference="GC-0001", created_by="manager",
    )
    await db_session.commit()

    balance = await get_balance(db_session, restaurant_id=restaurant.id, phone="+971500000001")
    assert balance == Decimal("100.00")


@pytest.mark.anyio
async def test_duplicate_purchase_reference_does_not_double_credit(db_session, restaurant):
    for _ in range(2):
        await purchase_gift_card(
            db_session, restaurant_id=restaurant.id, recipient_phone="+971500000002",
            amount_aed=Decimal("50.00"), purchase_reference="GC-0002", created_by="manager",
        )
        await db_session.commit()

    balance = await get_balance(db_session, restaurant_id=restaurant.id, phone="+971500000002")
    assert balance == Decimal("50.00")


@pytest.mark.anyio
async def test_balance_zero_for_unknown_phone(db_session, restaurant):
    balance = await get_balance(db_session, restaurant_id=restaurant.id, phone="+971500009999")
    assert balance == Decimal("0.00")
