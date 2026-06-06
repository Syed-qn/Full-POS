from datetime import UTC, datetime

from app.predictions.features import build_observations
from app.predictions.rolling import RollingAverageModel


def _ts(y, m, d, h):
    return datetime(y, m, d, h, 0, tzinfo=UTC)


def test_rolling_predicts_weekday_hour_mean_per_dish():
    items = [
        {"dish_id": 1, "qty": 3, "ordered_at": _ts(2026, 5, 4, 13)},   # Mon
        {"dish_id": 1, "qty": 5, "ordered_at": _ts(2026, 5, 11, 13)},  # Mon
        {"dish_id": 1, "qty": 4, "ordered_at": _ts(2026, 5, 18, 13)},  # Mon
    ]
    model = RollingAverageModel()
    model.fit(build_observations(items))
    pred = model.predict_dish_hour(dish_id=1, dow=0, hour=13)
    assert pred.expected_qty == 4.0  # mean(3,5,4)
    assert pred.model_version.startswith("rolling-")


def test_rolling_cold_start_falls_back_to_global_dish_mean():
    items = [{"dish_id": 1, "qty": 10, "ordered_at": _ts(2026, 5, 4, 19)}]  # only Mon 19:00
    model = RollingAverageModel()
    model.fit(build_observations(items))
    # unseen (Tue 09:00) bucket → fall back to dish's overall mean (10), not 0
    pred = model.predict_dish_hour(dish_id=1, dow=1, hour=9)
    assert pred.expected_qty == 10.0
    # unseen dish entirely → 0.0
    assert model.predict_dish_hour(dish_id=99, dow=1, hour=9).expected_qty == 0.0
