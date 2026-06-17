"""Pure feature builder for demand forecasting (no DB, model-agnostic).

The service layer queries raw order-item rows and hands plain dicts in; these
functions turn them into per-(dish, day-of-week, hour) observations and feature
vectors. Numpy is used only where it pays off (means); aggregation is plain dict.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type

import numpy as np

# Column order of feature_vector(); document for downstream models.
FEATURE_COLUMNS = ["hour", "dow", "is_weekend", "is_ramadan", "is_holiday", "weather_bad"]

# UAE weekend: Friday(4) and Saturday(5) under Python's Mon=0 weekday() convention.
_WEEKEND_DOWS = {4, 5}


@dataclass(frozen=True)
class DishHourObservation:
    dish_id: int
    dow: int
    hour: int
    qty: int
    date: date_type


def build_observations(order_items: list[dict]) -> list[DishHourObservation]:
    """Group raw order items by (dish_id, date, dow, hour) and sum qty.

    Each item is a dict with ``dish_id``, ``qty`` and a tz-aware ``ordered_at``
    datetime. ``dow = ordered_at.weekday()`` (Mon=0), ``hour = ordered_at.hour``.
    """
    buckets: dict[tuple[int, date_type, int, int], int] = defaultdict(int)
    for item in order_items:
        ordered_at = item["ordered_at"]
        key = (item["dish_id"], ordered_at.date(), ordered_at.weekday(), ordered_at.hour)
        buckets[key] += item["qty"]
    return [
        DishHourObservation(dish_id=dish_id, dow=dow, hour=hour, qty=qty, date=day)
        for (dish_id, day, dow, hour), qty in buckets.items()
    ]


def trailing_demand(
    observations: list[DishHourObservation], *, dish_id: int, dow: int, hour: int
) -> float:
    """Mean qty across observations matching the (dish, dow, hour) bucket.

    Returns ``0.0`` when no observation matches.
    """
    qtys = [
        o.qty
        for o in observations
        if o.dish_id == dish_id and o.dow == dow and o.hour == hour
    ]
    if not qtys:
        return 0.0
    return float(np.mean(qtys))


def feature_vector(
    dish_id: int,
    dow: int,
    hour: int,
    *,
    is_ramadan: int = 0,
    is_holiday: int = 0,
    weather_bad: int = 0,
) -> np.ndarray:
    """Return the feature row in ``FEATURE_COLUMNS`` order.

    Ramadan/holiday/weather flags are optional passthrough columns (default 0)
    so a richer future model can use them without an interface change.
    """
    is_weekend = 1 if dow in _WEEKEND_DOWS else 0
    return np.array(
        [hour, dow, is_weekend, is_ramadan, is_holiday, weather_bad],
        dtype=float,
    )
