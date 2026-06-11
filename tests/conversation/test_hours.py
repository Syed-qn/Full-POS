"""Unit tests for the business-hours helper (pure, no DB/clock)."""
from datetime import datetime, timezone

from app.conversation.hours import is_open, next_opening_label

# 2024-01-01 is a Monday (weekday()==0). Dubai is UTC+4.
_MON_09_DUBAI = datetime(2024, 1, 1, 5, 0, tzinfo=timezone.utc)   # 09:00 Dubai Mon
_MON_13_DUBAI = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)   # 13:00 Dubai Mon

_MON_OPEN = {"tz": "Asia/Dubai", "days": {"0": ["11:00", "23:00"]}}


def test_empty_config_is_always_open():
    assert is_open(None, _MON_09_DUBAI) is True
    assert is_open({}, _MON_09_DUBAI) is True
    assert is_open({"days": {}}, _MON_09_DUBAI) is True
    assert next_opening_label(None, _MON_09_DUBAI) is None


def test_closed_before_opening_then_open():
    assert is_open(_MON_OPEN, _MON_09_DUBAI) is False   # 09:00 < 11:00
    assert is_open(_MON_OPEN, _MON_13_DUBAI) is True     # 13:00 within 11-23


def test_next_opening_today_label():
    assert next_opening_label(_MON_OPEN, _MON_09_DUBAI) == "11:00 AM"


def test_next_opening_tomorrow_label():
    tue_only = {"tz": "Asia/Dubai", "days": {"1": ["11:00", "23:00"]}}
    # Monday: closed today, opens tomorrow (Tuesday)
    assert is_open(tue_only, _MON_09_DUBAI) is False
    assert next_opening_label(tue_only, _MON_09_DUBAI) == "tomorrow 11:00 AM"


def test_next_opening_weekday_label():
    thu_only = {"tz": "Asia/Dubai", "days": {"3": ["11:00", "23:00"]}}
    assert next_opening_label(thu_only, _MON_09_DUBAI) == "Thursday 11:00 AM"


def test_invalid_window_treated_as_closed():
    # close <= open ⇒ closed all day
    bad = {"days": {"0": ["23:00", "11:00"]}}
    assert is_open(bad, _MON_13_DUBAI) is False
