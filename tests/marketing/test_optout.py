import pytest

from app.marketing.optout import is_opted_out, is_stop_keyword, record_opt_out


@pytest.mark.parametrize(
    "text",
    [
        "STOP",
        " stop ",
        "Unsubscribe",
        "stop sending",
        "opt out",
        "OPTOUT",
        "cancel",
        "توقف",
    ],
)
def test_is_stop_keyword_true(text):
    assert is_stop_keyword(text) is True


@pytest.mark.parametrize(
    "text",
    ["stomp", "please continue", "biryani please", "", "   "],
)
def test_is_stop_keyword_false(text):
    assert is_stop_keyword(text) is False


async def test_record_then_is_opted_out(db_session, restaurant):
    phone = "+971500000001"
    assert await is_opted_out(
        db_session, restaurant_id=restaurant.id, phone=phone
    ) is False

    row = await record_opt_out(
        db_session, restaurant_id=restaurant.id, phone=phone
    )
    assert row.id is not None
    assert row.source == "stop_keyword"

    assert await is_opted_out(
        db_session, restaurant_id=restaurant.id, phone=phone
    ) is True


async def test_record_opt_out_idempotent(db_session, restaurant):
    phone = "+971500000002"
    first = await record_opt_out(
        db_session, restaurant_id=restaurant.id, phone=phone
    )
    # Calling twice must not raise (ON CONFLICT DO NOTHING) and returns same row.
    second = await record_opt_out(
        db_session, restaurant_id=restaurant.id, phone=phone
    )
    assert first.id == second.id
    assert await is_opted_out(
        db_session, restaurant_id=restaurant.id, phone=phone
    ) is True


async def test_opt_out_is_tenant_scoped(db_session, restaurant):
    phone = "+971500000003"
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone=phone)
    # A different restaurant_id is not affected.
    assert await is_opted_out(
        db_session, restaurant_id=restaurant.id + 99999, phone=phone
    ) is False
