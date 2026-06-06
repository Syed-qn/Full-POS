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
