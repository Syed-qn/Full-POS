"""RFM bucket classification — pure formula, no DB.

Guards the mutually-exclusive assignment so the Segment pill counts stay
trustworthy (each customer in exactly one bucket; named buckets sum to total).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.marketing.rfm import RFM_SEGMENTS, VALID_KEYS, _classify

NOW = datetime(2026, 6, 25, 12, 0, tzinfo=timezone.utc)


def _at(days_ago: int) -> datetime:
    return NOW - timedelta(days=days_ago)


@pytest.mark.parametrize(
    "total_orders, days_ago, expected",
    [
        (0, None, "new"),          # never ordered
        (1, 2, "new"),             # first-timer
        (6, 10, "champions"),      # frequent + recent
        (5, 30, "champions"),      # boundary recency
        (3, 40, "loyal"),          # frequent-ish + fairly recent
        (2, 10, "potential"),      # repeat buyer, recent, not yet frequent
        (2, 90, "at_risk"),        # repeat buyer going quiet
        (4, 200, "lost"),          # long lapsed
        (3, None, "lost"),         # F>1 but no recency signal
    ],
)
def test_classify_buckets(total_orders, days_ago, expected):
    last = None if days_ago is None else _at(days_ago)
    assert _classify(total_orders=total_orders, last_order_at=last, now=NOW) == expected


def test_every_bucket_key_is_valid_and_unique():
    keys = [k for k, _ in RFM_SEGMENTS]
    assert len(keys) == len(set(keys))
    assert set(keys) == VALID_KEYS
    assert "all" in VALID_KEYS


def test_classify_never_returns_all_or_unknown():
    # "all" is the whole base, never a classification result.
    for f in range(0, 8):
        for r in (None, 0, 15, 45, 90, 150):
            last = None if r is None else _at(r)
            bucket = _classify(total_orders=f, last_order_at=last, now=NOW)
            assert bucket in VALID_KEYS and bucket != "all"
