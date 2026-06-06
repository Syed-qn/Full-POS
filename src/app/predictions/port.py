from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.predictions.features import DishHourObservation


@dataclass(frozen=True)
class DishHourForecast:
    dish_id: int
    dow: int
    hour: int
    expected_qty: float
    model_version: str


@runtime_checkable
class ForecastModel(Protocol):
    """Swap seam: RollingAverageModel today; LightGBM/sklearn/prophet later, no call-site change."""

    def fit(self, observations: list[DishHourObservation]) -> None: ...

    def predict_dish_hour(self, *, dish_id: int, dow: int, hour: int) -> DishHourForecast: ...
