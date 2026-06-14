from app.marketing.optout import is_optout_intent, record_opt_in, is_opted_out, record_opt_out


def test_natural_phrase_triggers_optout():
    assert is_optout_intent("stop sending me marketing messages") is True


def test_dont_send_triggers_optout():
    assert is_optout_intent("don't send me any more messages") is True


def test_no_more_marketing_triggers_optout():
    assert is_optout_intent("no more marketing please") is True


def test_opt_out_phrase_triggers_optout():
    assert is_optout_intent("I want to opt out") is True


def test_ordering_message_not_optout():
    assert is_optout_intent("I want to order biryani") is False


def test_empty_string_not_optout():
    assert is_optout_intent("") is False


def test_case_insensitive():
    assert is_optout_intent("STOP SENDING ME MESSAGES") is True


def test_exact_stop_not_handled_here():
    # "stop" alone is handled by is_stop_keyword, not is_optout_intent
    # is_optout_intent only matches multi-word phrases
    assert is_optout_intent("stop") is False


async def test_record_opt_in_removes_optout_row(db_session, restaurant):
    await record_opt_out(db_session, restaurant_id=restaurant.id, phone="+971501111111")
    await db_session.commit()
    assert await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501111111")

    await record_opt_in(db_session, restaurant_id=restaurant.id, phone="+971501111111")
    await db_session.commit()
    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971501111111")


async def test_record_opt_in_is_idempotent_when_no_row(db_session, restaurant):
    # calling record_opt_in when not opted out should not raise
    await record_opt_in(db_session, restaurant_id=restaurant.id, phone="+971509999999")
    await db_session.commit()
    assert not await is_opted_out(db_session, restaurant_id=restaurant.id, phone="+971509999999")
