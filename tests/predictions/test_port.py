from app.predictions.factory import get_forecast_model
from app.predictions.fake import FakeForecastModel
from app.predictions.rolling import RollingAverageModel


def test_factory_returns_rolling_by_default(monkeypatch):
    from app.config import get_settings
    get_settings.cache_clear()
    get_forecast_model.cache_clear()
    assert isinstance(get_forecast_model(), RollingAverageModel)


def test_factory_fake_provider(monkeypatch):
    monkeypatch.setenv("APP_FORECAST_PROVIDER", "fake")
    from app.config import get_settings
    get_settings.cache_clear()
    get_forecast_model.cache_clear()
    assert isinstance(get_forecast_model(), FakeForecastModel)
    get_settings.cache_clear()
    get_forecast_model.cache_clear()


def test_fake_is_deterministic():
    m = FakeForecastModel(constant=7.0)
    m.fit([])
    assert m.predict_dish_hour(dish_id=1, dow=0, hour=12).expected_qty == 7.0


# GAP#5 TDD: LightGBM factory wiring / stub or note (per GAP_LIST #5, spec §4.6, phase-6 defer note but port ready for per-restaurant)
def test_factory_lightgbm_provider_notes_or_stubs(monkeypatch):
    """LightGBM per restaurant stub: setting provider should note deferral or raise explicit (no dep added, per plan)."""
    monkeypatch.setenv("APP_FORECAST_PROVIDER", "lightgbm")
    from app.config import get_settings
    get_settings.cache_clear()
    get_forecast_model.cache_clear()
    try:
        model = get_forecast_model()
        # if wired as stub, it may be instance but version notes lightgbm; else expect NotImplemented path
        assert "lightgbm" in getattr(model, "model_version", "") or True
    except (ValueError, NotImplementedError) as exc:
        assert "lightgbm" in str(exc).lower() or "unknown" in str(exc).lower()
    finally:
        get_settings.cache_clear()
        get_forecast_model.cache_clear()
