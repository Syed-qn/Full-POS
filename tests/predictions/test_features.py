from datetime import UTC, datetime

from app.predictions.features import (
    DishHourObservation,
    build_observations,
    trailing_demand,
)


def _ts(y, m, d, h):
    return datetime(y, m, d, h, 0, tzinfo=UTC)


def test_build_observations_buckets_by_dish_dow_hour():
    # two lunch orders for dish 1 on the same Monday hour, one for dish 2
    order_items = [
        {"dish_id": 1, "qty": 2, "ordered_at": _ts(2026, 6, 1, 13)},  # Mon
        {"dish_id": 1, "qty": 1, "ordered_at": _ts(2026, 6, 1, 13)},
        {"dish_id": 2, "qty": 4, "ordered_at": _ts(2026, 6, 1, 13)},
    ]
    obs = build_observations(order_items)
    by_key = {(o.dish_id, o.dow, o.hour): o for o in obs}
    assert by_key[(1, 0, 13)].qty == 3   # Mon=dow 0, summed qty
    assert by_key[(2, 0, 13)].qty == 4
    assert all(isinstance(o, DishHourObservation) for o in obs)


def test_trailing_demand_averages_matching_buckets():
    obs = [
        DishHourObservation(dish_id=1, dow=0, hour=13, qty=3, date=_ts(2026, 6, 1, 13).date()),
        DishHourObservation(dish_id=1, dow=0, hour=13, qty=5, date=_ts(2026, 5, 25, 13).date()),
        DishHourObservation(dish_id=1, dow=0, hour=13, qty=4, date=_ts(2026, 5, 18, 13).date()),
    ]
    # mean of 3,5,4 = 4.0 for Monday 13:00 dish 1
    assert trailing_demand(obs, dish_id=1, dow=0, hour=13) == 4.0
    # unseen bucket → 0.0
    assert trailing_demand(obs, dish_id=1, dow=2, hour=9) == 0.0
