"""Pure unit tests for the Today's Special send-time logic (no DB)."""

from app.marketing.todays_special import (
    WINDOW_END_MIN,
    WINDOW_START_MIN,
    desired_send_minute,
    is_due,
    is_personalized,
    parse_hhmm,
)
from app.ordering.service import OrderTimePrediction


def _pred(minute, count, conc):
    return OrderTimePrediction(minute_of_day=minute, order_count=count, concentration=conc)


def test_parse_hhmm():
    assert parse_hhmm("11:45", default=0) == 705
    assert parse_hhmm("00:00", default=99) == 0
    assert parse_hhmm("23:59", default=0) == 23 * 60 + 59
    assert parse_hhmm(None, default=705) == 705
    assert parse_hhmm("oops", default=705) == 705
    assert parse_hhmm("25:00", default=705) == 705  # invalid hour → default


def test_is_personalized_requires_clustered_history():
    assert is_personalized(_pred(720, 3, 0.9)) is True
    assert is_personalized(_pred(720, 2, 0.9)) is False  # too few orders
    assert is_personalized(_pred(720, 5, 0.2)) is False  # too scattered
    assert is_personalized(None) is False


def test_desired_send_minute_personalized_subtracts_lead():
    # Clustered noon habit (12:00 = 720) with 15-min lead → 11:45 = 705.
    pred = _pred(720, 4, 0.95)
    assert desired_send_minute(pred, lead_minutes=15, default_minute=600) == 705


def test_desired_send_minute_falls_back_to_default():
    # Only one order → not personalized → use the restaurant default time.
    pred = _pred(720, 1, 0.99)
    assert desired_send_minute(pred, lead_minutes=15, default_minute=690) == 690
    assert desired_send_minute(None, lead_minutes=15, default_minute=690) == 690


def test_desired_send_minute_clamps_to_window():
    # A 2am habit (120) minus lead is far before 9am → clamp up to window open.
    assert desired_send_minute(_pred(120, 5, 0.99), lead_minutes=15, default_minute=600) == WINDOW_START_MIN
    # A 11pm habit (1380) is after the window → clamp down to last sendable minute.
    assert desired_send_minute(_pred(1380, 5, 0.99), lead_minutes=15, default_minute=600) == WINDOW_END_MIN - 1


def test_is_due_window():
    # Due from the target minute up to (but not including) target + max_late.
    assert is_due(705, 705, max_late_minutes=90) is True
    assert is_due(705, 700, max_late_minutes=90) is False  # before target
    assert is_due(705, 794, max_late_minutes=90) is True   # 89 min late, still due
    assert is_due(705, 795, max_late_minutes=90) is False  # too late, skip
