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


def test_fee_settings_from_restaurant_converts_and_drives_calc():
    from app.ordering.fees import fee_settings_from_restaurant

    s = {"delivery_fee_tiers": [{"max_km": 1, "fee_aed": 0}, {"max_km": 4, "fee_aed": 9}]}
    conv = fee_settings_from_restaurant(s)
    assert conv == {"tiers": [{"max_km": 1.0, "fee": "0"}, {"max_km": 4.0, "fee": "9"}]}
    # The converted settings drive the fee + radius dynamically.
    assert calculate_fee(0.5, conv) == Decimal("0")
    assert calculate_fee(2.5, conv) == Decimal("9")
    with pytest.raises(UndeliverableError):
        calculate_fee(4.5, conv)   # beyond the 4 km top tier = out of radius


def test_fee_settings_none_when_unconfigured_or_malformed():
    from app.ordering.fees import fee_settings_from_restaurant

    assert fee_settings_from_restaurant(None) is None
    assert fee_settings_from_restaurant({}) is None
    assert fee_settings_from_restaurant({"delivery_fee_tiers": []}) is None
    # missing fee_aed → malformed → fall back to spec defaults (None)
    assert fee_settings_from_restaurant({"delivery_fee_tiers": [{"max_km": 3}]}) is None


def test_delivery_info_text_defaults_match_spec():
    from app.ordering.fees import delivery_info_text

    # Spec tiers — the exact line the bot must recite (no 1E+1 sci-notation,
    # correct 3/5/10 km thresholds). This is the fee-hallucination regression.
    assert delivery_info_text(None) == (
        "Delivery: free within 3 km, AED 5 for 3-5 km, AED 10 for 5-10 km. "
        "We deliver up to 10 km."
    )


def test_delivery_info_text_uses_restaurant_tiers():
    from app.ordering.fees import delivery_info_text

    s = {"delivery_fee_tiers": [
        {"max_km": 2, "fee_aed": 0},
        {"max_km": 6, "fee_aed": 7},
        {"max_km": 12, "fee_aed": 15},
    ]}
    assert delivery_info_text(s) == (
        "Delivery: free within 2 km, AED 7 for 2-6 km, AED 15 for 6-12 km. "
        "We deliver up to 12 km."
    )


def test_delivery_info_text_no_scientific_notation():
    from app.ordering.fees import delivery_info_text

    # fee_aed 10 stored as "10.00" must render "AED 10", never "AED 1E+1".
    s = {"delivery_fee_tiers": [{"max_km": 5, "fee_aed": 10}]}
    out = delivery_info_text(s)
    assert "AED 10" in out
    assert "E+" not in out


def test_settings_patch_validates_tiers():
    from app.identity.schemas import SettingsPatch

    with pytest.raises(ValueError):
        SettingsPatch(delivery_fee_tiers=[{"max_km": 3}])            # missing fee_aed
    with pytest.raises(ValueError):
        SettingsPatch(delivery_fee_tiers=[])                          # empty
    with pytest.raises(ValueError):
        SettingsPatch(delivery_fee_tiers=[                            # not ascending
            {"max_km": 5, "fee_aed": 0}, {"max_km": 3, "fee_aed": 5},
        ])
    ok = SettingsPatch(delivery_fee_tiers=[{"max_km": 3, "fee_aed": 0}])
    assert ok.delivery_fee_tiers
