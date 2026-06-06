from decimal import Decimal

import pytest

from app.geo.fees import OutOfRadiusError, delivery_fee_aed


def test_free_under_3km():
    assert delivery_fee_aed(0.5) == Decimal("0.00")
    assert delivery_fee_aed(3.0) == Decimal("0.00")  # boundary inclusive


def test_aed5_between_3_and_5km():
    assert delivery_fee_aed(3.01) == Decimal("5.00")
    assert delivery_fee_aed(5.0) == Decimal("5.00")  # boundary inclusive


def test_aed10_between_5_and_10km():
    assert delivery_fee_aed(5.01) == Decimal("10.00")
    assert delivery_fee_aed(10.0) == Decimal("10.00")  # boundary inclusive


def test_reject_over_10km():
    with pytest.raises(OutOfRadiusError):
        delivery_fee_aed(10.01)


def test_returns_decimal_type():
    assert isinstance(delivery_fee_aed(2.0), Decimal)
