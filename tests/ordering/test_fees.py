from decimal import Decimal

import pytest

from app.ordering.fees import UndeliverableError, calculate_fee


def test_fee_within_3km_is_free():
    assert calculate_fee(2.5) == Decimal("0.00")


def test_fee_exactly_3km_is_free():
    assert calculate_fee(3.0) == Decimal("0.00")


def test_fee_between_3_and_5km_is_5():
    assert calculate_fee(4.0) == Decimal("5.00")


def test_fee_exactly_5km_is_5():
    assert calculate_fee(5.0) == Decimal("5.00")


def test_fee_above_5km_is_10():
    assert calculate_fee(7.5) == Decimal("10.00")


def test_fee_exactly_10km_is_10():
    assert calculate_fee(10.0) == Decimal("10.00")


def test_beyond_10km_raises_undeliverable():
    with pytest.raises(UndeliverableError):
        calculate_fee(10.1)


def test_custom_tiers_from_settings():
    # Override tiers via settings dict — restaurant can configure different thresholds
    custom = {"tiers": [{"max_km": 5.0, "fee": "0.00"}, {"max_km": 10.0, "fee": "8.00"}]}
    assert calculate_fee(4.0, settings=custom) == Decimal("0.00")
    assert calculate_fee(8.0, settings=custom) == Decimal("8.00")
