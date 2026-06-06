# tests/webhook/test_replay.py
import datetime as dt

import pytest

from app.webhook.replay import ReplayError, assert_fresh


def test_fresh_timestamp_passes():
    now = dt.datetime.now(dt.timezone.utc)
    assert assert_fresh(int(now.timestamp()), window_seconds=300) is None


def test_stale_timestamp_rejected():
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=600)
    with pytest.raises(ReplayError):
        assert_fresh(int(old.timestamp()), window_seconds=300)


def test_future_skew_tolerated_within_window():
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=60)
    assert assert_fresh(int(future.timestamp()), window_seconds=300) is None


def test_far_future_rejected():
    future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=3600)
    with pytest.raises(ReplayError):
        assert_fresh(int(future.timestamp()), window_seconds=300)


def test_none_timestamp_skips():
    assert assert_fresh(None, window_seconds=300) is None
