"""Pure accuracy math for forecast scoring (no DB).

The nightly worker queries actual order counts and calls these helpers to
backfill ``prediction_runs.accuracy`` (1 - MAPE, clamped to [0, 1]).
"""


def mape(predicted: list[float], actual: list[float]) -> float:
    """Mean Absolute Percentage Error over paired points.

    ``mean(|p - a| / a)`` across pairs where ``a != 0`` (zero actuals are
    skipped to avoid divide-by-zero). Returns ``0.0`` when no valid pair exists.
    """
    apes = [abs(p - a) / a for p, a in zip(predicted, actual, strict=False) if a != 0]
    if not apes:
        return 0.0
    return sum(apes) / len(apes)


def accuracy_from_mape(m: float) -> float:
    """Convert MAPE to an accuracy score in [0, 1] (never negative).

    Rounded to 4 dp to match the ``Numeric(5, 4)`` storage column and to avoid
    binary-float artifacts (e.g. ``1.0 - 0.18`` → ``0.82000…1``).
    """
    return round(max(0.0, 1.0 - m), 4)


def score_prediction(predicted: dict, actual: dict) -> float:
    """Accuracy on the primary ``order_count`` metric.

    Dish-level multi-point MAPE is a follow-up; this stores the single primary
    metric for ``run.accuracy`` while dish detail lives in JSONB.
    """
    p = float(predicted["order_count"])
    a = float(actual["order_count"])
    return accuracy_from_mape(mape([p], [a]))
