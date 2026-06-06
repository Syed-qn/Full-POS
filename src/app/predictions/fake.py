"""Deterministic fake forecast model for service/worker/router tests."""

from app.predictions.features import DishHourObservation
from app.predictions.port import DishHourForecast


class FakeForecastModel:
    def __init__(self, constant: float = 0.0) -> None:
        self.constant = constant

    def fit(self, observations: list[DishHourObservation]) -> None:  # no-op
        return None

    def predict_dish_hour(self, *, dish_id: int, dow: int, hour: int) -> DishHourForecast:
        return DishHourForecast(
            dish_id=dish_id,
            dow=dow,
            hour=hour,
            expected_qty=self.constant,
            model_version="fake-1",
        )
