from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.predictions.models import ManagerOverride, ModelRegistry, PredictionRun


@pytest.mark.asyncio
async def test_prediction_run_roundtrip(db_session, restaurant):
    run = PredictionRun(
        restaurant_id=restaurant.id,
        horizon="lunch",
        target_date=datetime(2026, 6, 7, tzinfo=UTC).date(),
        predicted={"order_count": 42, "revenue": "1260.00",
                   "dish_demand": {"1": 18, "2": 9}, "avg_distance_km": 3.2},
        model_version="rolling-v1",
    )
    db_session.add(run)
    await db_session.flush()
    got = (await db_session.execute(select(PredictionRun))).scalar_one()
    assert got.horizon == "lunch"
    assert got.predicted["dish_demand"]["1"] == 18
    assert got.actual is None and got.accuracy is None  # backfilled later


@pytest.mark.asyncio
async def test_model_registry_and_override(db_session, restaurant):
    db_session.add(ModelRegistry(restaurant_id=restaurant.id, model_type="rolling",
                                 version="1", metrics={"mape": 0.18}))
    db_session.add(ManagerOverride(
        restaurant_id=restaurant.id,
        text="big corporate order Thursday lunch",
        parsed_effect={"horizon": "lunch", "dow": 3, "order_count_delta": 30},
        active_from=datetime(2026, 6, 7, tzinfo=UTC),
        active_to=datetime(2026, 6, 8, tzinfo=UTC),
    ))
    await db_session.flush()
