"""Pure-numpy rolling-average baseline forecast model.

Weekday x hour x dish rolling mean, with cold-start fallback to the dish's
overall mean. Implements the ForecastModel Protocol so a future
LightGBMForecastModel can drop in with zero call-site changes.
"""

from collections import defaultdict
from datetime import date

import numpy as np

from app.predictions.features import DishHourObservation
from app.predictions.port import DishHourForecast


class RollingAverageModel:
    def __init__(self) -> None:
        self._bucket_mean: dict[tuple[int, int, int], float] = {}
        self._dish_mean: dict[int, float] = {}
        self._fitted_at: date | None = None

    def fit(self, observations: list[DishHourObservation]) -> None:
        bucket_qtys: dict[tuple[int, int, int], list[int]] = defaultdict(list)
        dish_qtys: dict[int, list[int]] = defaultdict(list)
        for o in observations:
            bucket_qtys[(o.dish_id, o.dow, o.hour)].append(o.qty)
            dish_qtys[o.dish_id].append(o.qty)
        self._bucket_mean = {k: float(np.mean(v)) for k, v in bucket_qtys.items()}
        self._dish_mean = {k: float(np.mean(v)) for k, v in dish_qtys.items()}
        self._fitted_at = date.today()

    @property
    def model_version(self) -> str:
        stamp = self._fitted_at.isoformat() if self._fitted_at else "unfitted"
        return f"rolling-{stamp}"

    def predict_dish_hour(self, *, dish_id: int, dow: int, hour: int) -> DishHourForecast:
        expected = self._bucket_mean.get((dish_id, dow, hour))
        if expected is None:
            # cold-start: fall back to the dish's overall mean, else 0.0
            expected = self._dish_mean.get(dish_id, 0.0)
        return DishHourForecast(
            dish_id=dish_id,
            dow=dow,
            hour=hour,
            expected_qty=expected,
            model_version=self.model_version,
        )
