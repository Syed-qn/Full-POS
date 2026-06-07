from app.llm.fake import FakeForecastAdjuster
from app.predictions.adjust import apply_overrides


def test_apply_overrides_delta_and_mult():
    predicted = {"order_count": 40, "revenue": "1200.00", "dish_demand": {"1": 10}}
    effects = [
        {"order_count_delta": 30, "dish_demand_delta": {"1": 5}},
        {"order_count_mult": 1.0, "revenue_mult": 1.5},
    ]
    out, reasoning = apply_overrides(predicted, effects)
    assert out["order_count"] == 70           # 40 + 30
    assert out["dish_demand"]["1"] == 15       # 10 + 5
    assert out["revenue"] == "1800.00"         # 1200 * 1.5, 2dp Decimal string
    assert "override" in reasoning.lower()


def test_apply_overrides_noop_when_empty():
    predicted = {"order_count": 40, "revenue": "1200.00", "dish_demand": {}}
    out, reasoning = apply_overrides(predicted, [])
    assert out == predicted
    assert reasoning == ""


def test_apply_overrides_does_not_mutate_input():
    predicted = {"order_count": 40, "revenue": "1200.00", "dish_demand": {"1": 10}}
    apply_overrides(predicted, [{"order_count_delta": 5, "dish_demand_delta": {"1": 3}}])
    assert predicted["order_count"] == 40
    assert predicted["dish_demand"]["1"] == 10


def test_apply_overrides_count_mult_rounds_to_int():
    predicted = {"order_count": 40}
    out, _ = apply_overrides(predicted, [{"order_count_mult": 1.5}])
    assert out["order_count"] == 60


def test_apply_overrides_new_dish_id_from_delta():
    predicted = {"order_count": 10, "dish_demand": {"1": 4}}
    out, _ = apply_overrides(predicted, [{"dish_demand_delta": {"2": 7}}])
    assert out["dish_demand"]["2"] == 7
    assert out["dish_demand"]["1"] == 4


def test_fake_adjuster_parses_corporate_order_text():
    adj = FakeForecastAdjuster()
    effect = adj.parse_override("big corporate order Thursday lunch, expect 30 extra")
    assert effect["dow"] == 3            # Thursday
    assert effect["horizon"] == "lunch"
    assert effect["order_count_delta"] == 30


def test_fake_adjuster_double_keyword_sets_mult():
    adj = FakeForecastAdjuster()
    effect = adj.parse_override("dinner rush will double on Saturday")
    assert effect["dow"] == 5
    assert effect["horizon"] == "dinner"
    assert effect["order_count_mult"] == 2.0


def test_fake_adjuster_no_match_returns_empty():
    adj = FakeForecastAdjuster()
    assert adj.parse_override("nothing relevant here") == {}


def test_get_forecast_adjuster_returns_fake_when_provider_is_fake(monkeypatch):
    from app.config import get_settings
    from app.llm.factory import get_forecast_adjuster
    monkeypatch.setenv("APP_LLM_PROVIDER", "fake")
    get_settings.cache_clear()
    try:
        adj = get_forecast_adjuster()
        assert isinstance(adj, FakeForecastAdjuster)
    finally:
        get_settings.cache_clear()
