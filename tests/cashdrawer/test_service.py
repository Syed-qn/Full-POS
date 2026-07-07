from decimal import Decimal

import pytest

from app.cashdrawer.service import (
    DrawerAlreadyOpenError,
    add_event,
    close_session,
    get_current_session,
    open_session,
)


@pytest.mark.anyio
async def test_open_session_creates_open_row(db_session, restaurant):
    session = await open_session(
        db_session, restaurant_id=restaurant.id, opened_by="manager", opening_float_aed=Decimal("200.00")
    )
    await db_session.commit()
    assert session.status == "open"
    assert session.opening_float_aed == Decimal("200.00")


@pytest.mark.anyio
async def test_open_session_twice_rejected(db_session, restaurant):
    await open_session(
        db_session, restaurant_id=restaurant.id, opened_by="manager", opening_float_aed=Decimal("200.00")
    )
    await db_session.commit()
    with pytest.raises(DrawerAlreadyOpenError):
        await open_session(
            db_session, restaurant_id=restaurant.id, opened_by="manager", opening_float_aed=Decimal("100.00")
        )


@pytest.mark.anyio
async def test_get_current_session_returns_open_one(db_session, restaurant):
    opened = await open_session(
        db_session, restaurant_id=restaurant.id, opened_by="manager", opening_float_aed=Decimal("200.00")
    )
    await db_session.commit()
    current = await get_current_session(db_session, restaurant_id=restaurant.id)
    assert current.id == opened.id


@pytest.mark.anyio
async def test_get_current_session_none_when_no_open_session(db_session, restaurant):
    current = await get_current_session(db_session, restaurant_id=restaurant.id)
    assert current is None


@pytest.mark.anyio
async def test_close_session_computes_variance(db_session, restaurant):
    session = await open_session(
        db_session, restaurant_id=restaurant.id, opened_by="manager", opening_float_aed=Decimal("200.00")
    )
    await db_session.commit()
    await add_event(
        db_session, session_id=session.id, restaurant_id=restaurant.id,
        type="cash_in", amount_aed=Decimal("500.00"), reason="rider COD handover", created_by="manager",
    )
    await add_event(
        db_session, session_id=session.id, restaurant_id=restaurant.id,
        type="cash_out", amount_aed=Decimal("50.00"), reason="supplier payment", created_by="manager",
    )
    await db_session.commit()

    # expected = 200 + 500 - 50 = 650
    closed = await close_session(
        db_session, session_id=session.id, restaurant_id=restaurant.id,
        closed_by="manager", closing_count_aed=Decimal("645.00"),
    )
    await db_session.commit()
    assert closed.status == "closed"
    assert closed.variance_aed == Decimal("-5.00")
