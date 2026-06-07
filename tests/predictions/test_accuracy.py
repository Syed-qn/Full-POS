import math

from app.predictions.accuracy import TARGET_ACCURACY, accuracy_from_mape, mape, score_prediction


def test_mape_basic():
    # predicted 100, actual 80 → APE 0.25
    assert math.isclose(mape([100], [80]), 0.25)
    # multiple points averaged (APE relative to actual): 2/10 and 2/20
    assert math.isclose(mape([12, 18], [10, 20]), (0.2 + 0.1) / 2, rel_tol=1e-9)


def test_mape_skips_zero_actuals():
    # actual 0 would divide-by-zero → skipped; only the 100/80 pair counts
    assert math.isclose(mape([100, 5], [80, 0]), 0.25)


def test_accuracy_from_mape_clamped():
    assert accuracy_from_mape(0.18) == 0.82
    assert accuracy_from_mape(1.5) == 0.0   # never negative


def test_score_prediction_reads_order_count():
    predicted = {"order_count": 50, "revenue": "1500.00"}
    actual = {"order_count": 40, "revenue": "1300.00"}
    acc = score_prediction(predicted, actual)
    # uses order_count primary metric: APE = |50-40|/40 = 0.25 → accuracy 0.75
    assert math.isclose(acc, 0.75)


def test_target_accuracy_default_80pct():
    """~80% acc target per spec/GAP_LIST #5; const drives enforcement/check in run_forecast + retrain."""
    assert TARGET_ACCURACY == 0.8


def test_accuracy_below_target_is_flagged_by_score():
    """Example: low accuracy run (below target) should be detectable for retrain/alerts."""
    # predicted 100 vs actual 50 -> MAPE=1.0 -> acc=0.0 < 0.8
    acc = score_prediction({"order_count": 100}, {"order_count": 50})
    assert acc < TARGET_ACCURACY
    assert acc == 0.0
