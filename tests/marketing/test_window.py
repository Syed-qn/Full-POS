"""UAE marketing send-window checks (Asia/Dubai, 9am-6pm by UAE Cabinet 56/2024)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.marketing.window import is_within_uae_window, next_window_open

DUBAI = ZoneInfo("Asia/Dubai")


def _dubai(year, month, day, hour, minute=0) -> datetime:
    """A UTC instant corresponding to the given Asia/Dubai wall-clock time."""
    local = datetime(year, month, day, hour, minute, tzinfo=DUBAI)
    return local.astimezone(timezone.utc)


def test_before_window_is_false():
    assert is_within_uae_window(_dubai(2026, 6, 6, 8, 59)) is False


def test_window_open_boundary_is_true():
    assert is_within_uae_window(_dubai(2026, 6, 6, 9, 0)) is True


def test_window_last_minute_is_true():
    assert is_within_uae_window(_dubai(2026, 6, 6, 17, 59)) is True


def test_window_close_boundary_is_false():
    assert is_within_uae_window(_dubai(2026, 6, 6, 18, 0)) is False


def test_utc_instant_inside_window():
    # 09:30 Dubai == 05:30 UTC (UTC+4).
    instant = datetime(2026, 6, 6, 5, 30, tzinfo=timezone.utc)
    assert is_within_uae_window(instant) is True


def test_next_window_open_after_close_is_next_day_9am():
    # 20:00 Dubai → next day 09:00 Dubai, returned in UTC (05:00 UTC).
    now = _dubai(2026, 6, 6, 20, 0)
    nxt = next_window_open(now)
    local = nxt.astimezone(DUBAI)
    assert local.hour == 9
    assert local.minute == 0
    assert local.date() == datetime(2026, 6, 7).date()
    assert nxt.tzinfo is not None


def test_next_window_open_before_open_is_same_day_9am():
    now = _dubai(2026, 6, 6, 6, 0)
    nxt = next_window_open(now)
    local = nxt.astimezone(DUBAI)
    assert local.hour == 9
    assert local.date() == datetime(2026, 6, 6).date()
