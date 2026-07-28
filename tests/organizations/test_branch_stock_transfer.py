"""Two-phase stock transfer between branches.

Stock leaves one branch, spends time in a van, and arrives at another. The old
HQ-only flow applied both ends at one instant, which means the same kilos are
either in both branches at once or in neither — and it was locked to the owner,
so the manager who actually loads the van could not record it.
"""
from decimal import Decimal

import pytest

from app.identity.auth import hash_password
from app.identity.models import Restaurant
from app.inventory.models import Ingredient
from app.organizations.models import Organization


async def _org_with_two_branches(db_session):
    org = Organization(
        name="La Cafe Group",
        owner_email="owner@lacafe.ae",
        password_hash=hash_password("hunter2!"),
    )
    db_session.add(org)
    await db_session.flush()

    branches = []
    for name in ("Deira", "Marina"):
        branch = Restaurant(
            name=name,
            phone=f"+9714000{len(branches)}",
            password_hash=hash_password("hunter2!"),
            lat=25.2,
            lng=55.2,
            organization_id=org.id,
        )
        db_session.add(branch)
        branches.append(branch)
    await db_session.flush()
    return org, branches[0], branches[1]


async def _stock(db_session, branch, name, qty, unit="kg"):
    row = Ingredient(
        restaurant_id=branch.id,
        name=name,
        unit=unit,
        current_stock=Decimal(qty),
        low_stock_threshold=Decimal("1.000"),
    )
    db_session.add(row)
    await db_session.flush()
    return row


@pytest.mark.anyio
async def test_dispatch_removes_it_here_and_receive_adds_it_there(db_session):
    from app.organizations.stock_transfer_branch import (
        dispatch_stock_transfer,
        receive_stock_transfer,
    )

    _, deira, marina = await _org_with_two_branches(db_session)
    source = await _stock(db_session, deira, "Chicken", "30.000")

    transfer = await dispatch_stock_transfer(
        db_session,
        from_restaurant_id=deira.id,
        to_restaurant_id=marina.id,
        lines=[{"ingredient_name": "Chicken", "quantity": "10.000"}],
        dispatched_by="manager",
    )
    # Gone from the sender the moment the van leaves. A branch that can still
    # see it on screen will plan to cook with it.
    assert transfer.status == "in_transit"
    assert source.current_stock == Decimal("20.000")

    # ...and NOT yet at the destination. This is the window the single-step
    # flow could not represent.
    from sqlalchemy import select

    dest = await db_session.scalar(
        select(Ingredient).where(
            Ingredient.restaurant_id == marina.id, Ingredient.name == "Chicken"
        )
    )
    assert dest is None

    await receive_stock_transfer(
        db_session,
        transfer_id=transfer.id,
        to_restaurant_id=marina.id,
        received_by="manager",
    )
    assert transfer.status == "completed"
    dest = await db_session.scalar(
        select(Ingredient).where(
            Ingredient.restaurant_id == marina.id, Ingredient.name == "Chicken"
        )
    )
    assert dest is not None, "a branch that does not stock the item yet gets it created"
    assert dest.current_stock == Decimal("10.000")
    assert source.current_stock == Decimal("20.000")


@pytest.mark.anyio
async def test_a_short_delivery_keeps_the_discrepancy(db_session):
    """Sent 10, got 8. The missing 2 must stay visible, not be rewritten."""
    from app.organizations.stock_transfer_branch import (
        dispatch_stock_transfer,
        receive_stock_transfer,
    )
    from sqlalchemy import select

    from app.organizations.models import StockTransferLine

    _, deira, marina = await _org_with_two_branches(db_session)
    await _stock(db_session, deira, "Rice", "50.000")
    await _stock(db_session, marina, "Rice", "5.000")

    transfer = await dispatch_stock_transfer(
        db_session,
        from_restaurant_id=deira.id,
        to_restaurant_id=marina.id,
        lines=[{"ingredient_name": "Rice", "quantity": "10.000"}],
        dispatched_by="manager",
    )
    await receive_stock_transfer(
        db_session,
        transfer_id=transfer.id,
        to_restaurant_id=marina.id,
        received_by="manager",
        received={"Rice": Decimal("8.000")},
    )

    line = await db_session.scalar(
        select(StockTransferLine).where(StockTransferLine.transfer_id == transfer.id)
    )
    assert line.quantity == Decimal("10.000"), "what was sent must not be rewritten"
    assert line.qty_received == Decimal("8.000")

    dest = await db_session.scalar(
        select(Ingredient).where(
            Ingredient.restaurant_id == marina.id, Ingredient.name == "Rice"
        )
    )
    # Only what turned up is added. The 2 kg gap is the loss, and inventing it
    # at the destination would hide exactly the thing this document exists to
    # catch.
    assert dest.current_stock == Decimal("13.000")


@pytest.mark.anyio
async def test_cannot_send_more_than_you_have(db_session):
    from app.organizations.stock_transfer_branch import dispatch_stock_transfer

    _, deira, marina = await _org_with_two_branches(db_session)
    source = await _stock(db_session, deira, "Saffron", "2.000", unit="g")

    with pytest.raises(ValueError, match="only 2.000"):
        await dispatch_stock_transfer(
            db_session,
            from_restaurant_id=deira.id,
            to_restaurant_id=marina.id,
            lines=[{"ingredient_name": "Saffron", "quantity": "5.000"}],
            dispatched_by="manager",
        )
    assert source.current_stock == Decimal("2.000")


@pytest.mark.anyio
async def test_only_the_destination_can_receive(db_session):
    """A sender confirming its own delivery would defeat the whole control."""
    from app.organizations.stock_transfer_branch import (
        dispatch_stock_transfer,
        receive_stock_transfer,
    )

    _, deira, marina = await _org_with_two_branches(db_session)
    await _stock(db_session, deira, "Oil", "20.000", unit="litre")

    transfer = await dispatch_stock_transfer(
        db_session,
        from_restaurant_id=deira.id,
        to_restaurant_id=marina.id,
        lines=[{"ingredient_name": "Oil", "quantity": "5.000"}],
        dispatched_by="manager",
    )
    with pytest.raises(ValueError, match="only the destination branch"):
        await receive_stock_transfer(
            db_session,
            transfer_id=transfer.id,
            to_restaurant_id=deira.id,
            received_by="manager",
        )
    # Positive control: the real destination still can, so the failure above
    # means "not yours" and not "endpoint broken".
    await receive_stock_transfer(
        db_session,
        transfer_id=transfer.id,
        to_restaurant_id=marina.id,
        received_by="manager",
    )
    assert transfer.status == "completed"


@pytest.mark.anyio
async def test_cancel_returns_the_stock_and_only_before_arrival(db_session):
    from app.organizations.stock_transfer_branch import (
        cancel_stock_transfer,
        dispatch_stock_transfer,
        receive_stock_transfer,
    )

    _, deira, marina = await _org_with_two_branches(db_session)
    source = await _stock(db_session, deira, "Flour", "40.000")

    transfer = await dispatch_stock_transfer(
        db_session,
        from_restaurant_id=deira.id,
        to_restaurant_id=marina.id,
        lines=[{"ingredient_name": "Flour", "quantity": "10.000"}],
        dispatched_by="manager",
    )
    assert source.current_stock == Decimal("30.000")

    await cancel_stock_transfer(
        db_session, transfer_id=transfer.id, from_restaurant_id=deira.id
    )
    assert transfer.status == "cancelled"
    assert source.current_stock == Decimal("40.000"), "the stock comes back"

    # A cancelled transfer cannot then be received — that would add stock at the
    # far end that has already been returned to the sender.
    with pytest.raises(ValueError, match="cannot receive"):
        await receive_stock_transfer(
            db_session,
            transfer_id=transfer.id,
            to_restaurant_id=marina.id,
            received_by="manager",
        )


@pytest.mark.anyio
async def test_cannot_cancel_after_it_has_been_accepted(db_session):
    """Taking it back afterwards would silently overdraw the other branch."""
    from app.organizations.stock_transfer_branch import (
        cancel_stock_transfer,
        dispatch_stock_transfer,
        receive_stock_transfer,
    )

    _, deira, marina = await _org_with_two_branches(db_session)
    await _stock(db_session, deira, "Sugar", "20.000")

    transfer = await dispatch_stock_transfer(
        db_session,
        from_restaurant_id=deira.id,
        to_restaurant_id=marina.id,
        lines=[{"ingredient_name": "Sugar", "quantity": "5.000"}],
        dispatched_by="manager",
    )
    await receive_stock_transfer(
        db_session,
        transfer_id=transfer.id,
        to_restaurant_id=marina.id,
        received_by="manager",
    )
    with pytest.raises(ValueError, match="cannot cancel"):
        await cancel_stock_transfer(
            db_session, transfer_id=transfer.id, from_restaurant_id=deira.id
        )


@pytest.mark.anyio
async def test_cannot_transfer_to_another_organization(db_session):
    """The one operation that reaches outside your own restaurant on purpose."""
    from app.organizations.stock_transfer_branch import dispatch_stock_transfer

    _, deira, _marina = await _org_with_two_branches(db_session)
    await _stock(db_session, deira, "Butter", "10.000")

    outsider = Restaurant(
        name="Someone Else",
        phone="+971499999999",
        password_hash=hash_password("hunter2!"),
        lat=25.2,
        lng=55.2,
    )
    db_session.add(outsider)
    await db_session.flush()

    with pytest.raises(ValueError, match="same organization"):
        await dispatch_stock_transfer(
            db_session,
            from_restaurant_id=deira.id,
            to_restaurant_id=outsider.id,
            lines=[{"ingredient_name": "Butter", "quantity": "1.000"}],
            dispatched_by="manager",
        )


@pytest.mark.anyio
async def test_sibling_branches_lists_the_others_and_never_outsiders(db_session):
    """What the destination picker is filled from, and what the dashboard uses
    to decide whether a Transfers tab exists at all."""
    from app.organizations.stock_transfer_branch import list_sibling_branches

    _, deira, marina = await _org_with_two_branches(db_session)
    outsider = Restaurant(
        name="Someone Else",
        phone="+971488888888",
        password_hash=hash_password("hunter2!"),
        lat=25.2,
        lng=55.2,
    )
    db_session.add(outsider)
    await db_session.flush()

    siblings = await list_sibling_branches(db_session, restaurant_id=deira.id)
    assert [b["name"] for b in siblings] == ["Marina"], "yourself and outsiders excluded"
    assert siblings[0]["id"] == marina.id

    # A restaurant in no organization has nobody to send to — the tab must stay
    # hidden rather than render an empty picker.
    assert await list_sibling_branches(db_session, restaurant_id=outsider.id) == []


@pytest.mark.anyio
async def test_list_shows_direction_from_this_branch_point_of_view(db_session):
    from app.organizations.stock_transfer_branch import (
        dispatch_stock_transfer,
        list_branch_transfers,
    )

    _, deira, marina = await _org_with_two_branches(db_session)
    await _stock(db_session, deira, "Milk", "30.000", unit="litre")

    await dispatch_stock_transfer(
        db_session,
        from_restaurant_id=deira.id,
        to_restaurant_id=marina.id,
        lines=[{"ingredient_name": "Milk", "quantity": "6.000"}],
        dispatched_by="manager",
    )

    sent = await list_branch_transfers(db_session, restaurant_id=deira.id)
    incoming = await list_branch_transfers(db_session, restaurant_id=marina.id)
    assert [t["direction"] for t in sent] == ["out"]
    assert [t["direction"] for t in incoming] == ["in"]
    # Branch NAMES, because "to_restaurant_id 7" tells a manager nothing.
    assert sent[0]["to_branch_name"] == "Marina"
    assert incoming[0]["from_branch_name"] == "Deira"
    assert sent[0]["lines"][0]["quantity"] == "6.000"
    assert sent[0]["lines"][0]["qty_received"] is None
