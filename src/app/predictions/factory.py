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
    if provider == "lightgbm":
        # GAP#5 / spec §4.6 / phase-6 plan: LightGBM per restaurant (full horizons, weekly retrain).
        # Port/protocol ready for drop-in (no call-site changes). Real impl + lightgbm dep deferred
        # (no heavy ML in phase-6 per plan; stub here to satisfy config + TDD test + "wire ... stub or note").
        # When ready: pip install lightgbm, add class LightGBMForecastModel(ForecastModel): ... per-rest fit.
        raise NotImplementedError(
            "LightGBMForecastModel (per-restaurant) not yet wired (GAP#5 task: note/stub only; "
            "requires extra deps + full model; use 'rolling' or 'fake' for now). "
            "See predictions/port.py Protocol + phase-6 plan deferral."
        )
    raise ValueError(f"Unknown forecast_provider: {provider!r}")
