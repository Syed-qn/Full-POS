from functools import lru_cache

from app.config import get_settings
from app.predictions.port import ForecastModel


@lru_cache
def get_forecast_model() -> ForecastModel:
    """Resolve the configured ForecastModel.

    NOTE: ``@lru_cache`` returns a singleton; ``fit()`` mutates it. The nightly
    worker must construct a fresh model per restaurant (use the factory only to
    resolve which class) or call ``get_forecast_model.cache_clear()`` before each
    fit to avoid stale state leaking across restaurants.
    """
    provider = get_settings().forecast_provider
    if provider == "rolling":
        from app.predictions.rolling import RollingAverageModel

        return RollingAverageModel()
    if provider == "fake":
        from app.predictions.fake import FakeForecastModel

        return FakeForecastModel()
    raise ValueError(f"Unknown forecast_provider: {provider!r}")
