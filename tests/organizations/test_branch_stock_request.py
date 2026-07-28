"""Asking another branch for stock — the first leg of request -> send -> receive.

The dispatch/receive pair in test_branch_stock_transfer.py covers a branch that
decides to send. This covers the branch that RUNS OUT, which is the one that
actually knows. Without it the holder has to guess, which in practice is a
phone call that leaves no record of what was asked for or whether it came.
"""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.identity.auth import hash_password
from app.identity.models import Restaurant
from app.organizations.models import StockTransferLine
from app.organizations.stock_transfer_branch import (
    approve_stock_transfer,
    decline_stock_transfer,
    request_stock_transfer,
    withdraw_stock_request,
)
from tests.organizations.test_branch_stock_transfer import _org_with_two_branches, _stock


@pytest.mark.anyio
async def test_a_request_moves_nothing_until_the_holder_agrees(db_session):
    """Asking must not be able to move another branch stock on its own."""
    _, deira, marina = await _org_with_two_branches(db_session)
    source = await _stock(db_session, deira, "Chicken", "30.000")

    transfer = await request_stock_transfer(
        db_session,
        requesting_restaurant_id=marina.id,
        from_restaurant_id=deira.id,
        lines=[{"ingredient_name": "Chicken", "quantity": "10.000"}],
        requested_by="manager",
    )
    assert transfer.status == "pending"
    # Stored the same way round as a dispatch — out of the holder, into the
    # asker — so nothing downstream special-cases which end is which.
    assert transfer.from_restaurant_id == deira.id
    assert transfer.to_restaurant_id == marina.id
    assert source.current_stock == Decimal("30.000"), "asking is not taking"

    await approve_stock_transfer(
        db_session,
        transfer_id=transfer.id,
        from_restaurant_id=deira.id,
        dispatched_by="manager",
    )
    assert transfer.status == "in_transit"
    assert source.current_stock == Decimal("20.000"), "the stock moves on approval"


@pytest.mark.anyio
async def test_sending_less_than_asked_keeps_both_numbers(db_session):
    """Asked 10, sent 6. Both survive, or the document claims 6 was all anyone
    ever wanted and the shortfall is invisible."""
    _, deira, marina = await _org_with_two_branches(db_session)
    source = await _stock(db_session, deira, "Rice", "20.000")

    transfer = await request_stock_transfer(
        db_session,
        requesting_restaurant_id=marina.id,
        from_restaurant_id=deira.id,
        lines=[{"ingredient_name": "Rice", "quantity": "10.000"}],
        requested_by="manager",
    )
    await approve_stock_transfer(
        db_session,
        transfer_id=transfer.id,
        from_restaurant_id=deira.id,
        dispatched_by="manager",
        quantities={"Rice": Decimal("6.000")},
    )

    line = await db_session.scalar(
        select(StockTransferLine).where(StockTransferLine.transfer_id == transfer.id)
    )
    assert line.qty_requested == Decimal("10.000")
    assert line.quantity == Decimal("6.000")
    assert source.current_stock == Decimal("14.000"), "only what was sent leaves"


@pytest.mark.anyio
async def test_cannot_approve_more_than_was_asked_for(db_session):
    """Otherwise approval becomes a way to push stock onto another branch."""
    _, deira, marina = await _org_with_two_branches(db_session)
    source = await _stock(db_session, deira, "Oil", "50.000", unit="litre")

    transfer = await request_stock_transfer(
        db_session,
        requesting_restaurant_id=marina.id,
        from_restaurant_id=deira.id,
        lines=[{"ingredient_name": "Oil", "quantity": "5.000"}],
        requested_by="manager",
    )
    with pytest.raises(ValueError, match="only 5.000 was asked for"):
        await approve_stock_transfer(
            db_session,
            transfer_id=transfer.id,
            from_restaurant_id=deira.id,
            dispatched_by="manager",
            quantities={"Oil": Decimal("40.000")},
        )
    assert source.current_stock == Decimal("50.000")
    assert transfer.status == "pending"


@pytest.mark.anyio
async def test_only_the_branch_being_asked_can_answer(db_session):
    """The asker approving their own request would be helping themselves to
    another branch store."""
    _, deira, marina = await _org_with_two_branches(db_session)
    await _stock(db_session, deira, "Flour", "30.000")

    transfer = await request_stock_transfer(
        db_session,
        requesting_restaurant_id=marina.id,
        from_restaurant_id=deira.id,
        lines=[{"ingredient_name": "Flour", "quantity": "5.000"}],
        requested_by="manager",
    )
    with pytest.raises(ValueError, match="only the branch being asked"):
        await approve_stock_transfer(
            db_session,
            transfer_id=transfer.id,
            from_restaurant_id=marina.id,
            dispatched_by="manager",
        )
    with pytest.raises(ValueError, match="only the branch being asked"):
        await decline_stock_transfer(
            db_session, transfer_id=transfer.id, from_restaurant_id=marina.id
        )
    # Positive control: the branch actually being asked still can, so the two
    # failures above mean "not yours" and not "endpoint broken".
    await decline_stock_transfer(
        db_session,
        transfer_id=transfer.id,
        from_restaurant_id=deira.id,
        reason="none spare",
    )
    assert transfer.status == "cancelled"
    assert "none spare" in (transfer.note or ""), "the asker needs to know why"


@pytest.mark.anyio
async def test_declining_moves_no_stock_and_closes_the_request(db_session):
    _, deira, marina = await _org_with_two_branches(db_session)
    source = await _stock(db_session, deira, "Sugar", "12.000")

    transfer = await request_stock_transfer(
        db_session,
        requesting_restaurant_id=marina.id,
        from_restaurant_id=deira.id,
        lines=[{"ingredient_name": "Sugar", "quantity": "4.000"}],
        requested_by="manager",
    )
    await decline_stock_transfer(
        db_session, transfer_id=transfer.id, from_restaurant_id=deira.id
    )
    assert source.current_stock == Decimal("12.000")
    # A declined request must not then be approvable, or "no" means nothing.
    with pytest.raises(ValueError, match="cannot approve"):
        await approve_stock_transfer(
            db_session,
            transfer_id=transfer.id,
            from_restaurant_id=deira.id,
            dispatched_by="manager",
        )


@pytest.mark.anyio
async def test_the_asker_can_withdraw_but_not_after_it_is_sent(db_session):
    _, deira, marina = await _org_with_two_branches(db_session)
    await _stock(db_session, deira, "Butter", "10.000")

    first = await request_stock_transfer(
        db_session,
        requesting_restaurant_id=marina.id,
        from_restaurant_id=deira.id,
        lines=[{"ingredient_name": "Butter", "quantity": "2.000"}],
        requested_by="manager",
    )
    await withdraw_stock_request(
        db_session, transfer_id=first.id, requesting_restaurant_id=marina.id
    )
    assert first.status == "cancelled"

    second = await request_stock_transfer(
        db_session,
        requesting_restaurant_id=marina.id,
        from_restaurant_id=deira.id,
        lines=[{"ingredient_name": "Butter", "quantity": "2.000"}],
        requested_by="manager",
    )
    await approve_stock_transfer(
        db_session,
        transfer_id=second.id,
        from_restaurant_id=deira.id,
        dispatched_by="manager",
    )
    # Once it is on the van it is a delivery, not a request. Withdrawing here
    # would leave stock deducted at Deira and never added at Marina.
    with pytest.raises(ValueError, match="cannot withdraw"):
        await withdraw_stock_request(
            db_session, transfer_id=second.id, requesting_restaurant_id=marina.id
        )


@pytest.mark.anyio
async def test_you_cannot_ask_a_branch_in_another_organization(db_session):
    _, _deira, marina = await _org_with_two_branches(db_session)
    outsider = Restaurant(
        name="Someone Else",
        phone="+971477777777",
        password_hash=hash_password("hunter2!"),
        lat=25.2,
        lng=55.2,
    )
    db_session.add(outsider)
    await db_session.flush()

    with pytest.raises(ValueError, match="same organization"):
        await request_stock_transfer(
            db_session,
            requesting_restaurant_id=marina.id,
            from_restaurant_id=outsider.id,
            lines=[{"ingredient_name": "Butter", "quantity": "1.000"}],
            requested_by="manager",
        )
