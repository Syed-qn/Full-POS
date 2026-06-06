"""Unit tests for marketing template naming (datestamp + 30-day blackout).

Pure functions — no DB, no settings. See plan Task 10 and
docs/research/meta-template-compliance.md §3.8 / §4.5.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.marketing.naming import (
    datestamped_name,
    is_name_reusable,
    next_available_name,
)

ON = date(2026, 6, 6)
NOW = datetime(2026, 6, 6, 9, 0, tzinfo=timezone.utc)


# --- datestamped_name: format correctness -------------------------------

def test_datestamped_name_basic():
    assert datestamped_name("daily_special", on=ON) == "daily_special_20260606"


def test_datestamped_name_with_suffix():
    assert datestamped_name("daily_special", on=ON, suffix=2) == "daily_special_20260606_2"


def test_datestamped_name_suffix_zero_omitted():
    # suffix=0 must NOT append _0
    assert datestamped_name("promo", on=ON, suffix=0) == "promo_20260606"


def test_datestamped_name_lowercases_and_sanitizes():
    # uppercase + spaces + punctuation collapse to single underscores
    assert datestamped_name("Daily Special!!", on=ON) == "daily_special_20260606"


def test_datestamped_name_collapses_repeated_underscores():
    assert datestamped_name("a---b   c", on=ON) == "a_b_c_20260606"


def test_datestamped_name_rejects_empty_prefix():
    with pytest.raises(ValueError):
        datestamped_name("!!!", on=ON)  # sanitizes to nothing


def test_datestamped_name_rejects_too_long():
    with pytest.raises(ValueError):
        datestamped_name("x" * 600, on=ON)


def test_datestamped_name_result_matches_pattern():
    import re

    name = datestamped_name("Café Brunch & Co.", on=ON)
    assert re.fullmatch(r"[a-z0-9_]+", name)


# --- is_name_reusable: 30-day blackout boundary -------------------------

def test_reusable_when_not_in_history():
    assert is_name_reusable("never_used", [], now=NOW) is True


def test_not_reusable_when_deleted_29_days_ago():
    deleted = NOW - timedelta(days=29)
    history = [("promo_x", deleted)]
    assert is_name_reusable("promo_x", history, now=NOW) is False


def test_reusable_when_deleted_31_days_ago():
    deleted = NOW - timedelta(days=31)
    history = [("promo_x", deleted)]
    assert is_name_reusable("promo_x", history, now=NOW) is True


def test_boundary_exactly_30_days_not_reusable():
    # within the last 30 days is inclusive of the 30-day mark
    deleted = NOW - timedelta(days=30)
    history = [("promo_x", deleted)]
    assert is_name_reusable("promo_x", history, now=NOW) is False


def test_reusable_uses_most_recent_deletion():
    history = [
        ("promo_x", NOW - timedelta(days=100)),
        ("promo_x", NOW - timedelta(days=5)),
    ]
    assert is_name_reusable("promo_x", history, now=NOW) is False


def test_reusable_ignores_other_names():
    history = [("other_name", NOW - timedelta(days=1))]
    assert is_name_reusable("promo_x", history, now=NOW) is True


# --- next_available_name: suffix collision ------------------------------

def test_next_available_name_suffix_zero_when_free():
    name = next_available_name(
        "daily_special", on=ON, deleted_history=[], existing_names=set(), now=NOW
    )
    assert name == "daily_special_20260606"


def test_next_available_name_skips_existing():
    existing = {"daily_special_20260606"}
    name = next_available_name(
        "daily_special", on=ON, deleted_history=[], existing_names=existing, now=NOW
    )
    assert name == "daily_special_20260606_1"


def test_next_available_name_skips_blackout():
    history = [("daily_special_20260606", NOW - timedelta(days=10))]
    name = next_available_name(
        "daily_special", on=ON, deleted_history=history, existing_names=set(), now=NOW
    )
    assert name == "daily_special_20260606_1"


def test_next_available_name_skips_both_existing_and_blackout():
    history = [("daily_special_20260606_1", NOW - timedelta(days=2))]
    existing = {"daily_special_20260606"}
    name = next_available_name(
        "daily_special", on=ON, deleted_history=history, existing_names=existing, now=NOW
    )
    assert name == "daily_special_20260606_2"
