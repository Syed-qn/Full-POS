"""Per-weekday, recency-weighted order-time habits.

Populates ``customers.usual_order_times`` JSONB and backs
``predict_order_time(..., weekday=)`` for marketing automations.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_DUBAI = ZoneInfo("Asia/Dubai")


@dataclass(frozen=True)
class OrderTimePrediction:
    """When a customer typically orders (Dubai minute-of-day + trust metrics)."""

    minute_of_day: int
    order_count: int
    concentration: float
RECENCY_HALF_LIFE_DAYS = 60.0


@dataclass(frozen=True)
class OrderStamp:
    """Single order clock position in Dubai local time."""

    hour: float  # hour + minute/60
    weekday: int  # 0=Monday
    age_days: float


def recency_weight(age_days: float, *, half_life_days: float = RECENCY_HALF_LIFE_DAYS) -> float:
    """Exponential decay — recent orders weigh more for habit drift."""
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def order_stamps_from_rows(
    rows: list[tuple[datetime | None, ...]],
    *,
    now_utc: datetime,
) -> list[OrderStamp]:
    """Build stamps from ``Order.created_at`` scalars."""
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    stamps: list[OrderStamp] = []
    for row in rows:
        created = row[0]
        if created is None:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        local = created.astimezone(_DUBAI)
        age = max(0.0, (now_utc - created).total_seconds() / 86400.0)
        stamps.append(
            OrderStamp(
                hour=local.hour + local.minute / 60.0,
                weekday=local.weekday(),
                age_days=age,
            )
        )
    return stamps


def _weighted_circular_stats(
    hours: list[float],
    weights: list[float],
) -> tuple[float, float] | None:
    if not hours or not weights or len(hours) != len(weights):
        return None
    total_w = sum(weights)
    if total_w <= 0:
        return None
    angles = [h / 24.0 * 2 * math.pi for h in hours]
    mean_sin = sum(w * math.sin(a) for w, a in zip(weights, angles)) / total_w
    mean_cos = sum(w * math.cos(a) for w, a in zip(weights, angles)) / total_w
    mean_angle = math.atan2(mean_sin, mean_cos)
    mean_hour = (mean_angle / (2 * math.pi) * 24.0) % 24.0
    resultant = math.hypot(mean_sin, mean_cos)
    return mean_hour, resultant


def predict_from_stamps(
    stamps: list[OrderStamp],
    *,
    weekday: int | None = None,
    apply_recency: bool = True,
) -> OrderTimePrediction | None:
    """Circular-mean prediction, optionally filtered to one weekday."""
    filtered = [s for s in stamps if weekday is None or s.weekday == weekday]
    if not filtered:
        return None
    hours = [s.hour for s in filtered]
    if apply_recency:
        weights = [recency_weight(s.age_days) for s in filtered]
    else:
        weights = [1.0] * len(filtered)
    stats = _weighted_circular_stats(hours, weights)
    if stats is None:
        return None
    mean_hour, resultant = stats
    return OrderTimePrediction(
        minute_of_day=round(mean_hour * 60) % 1440,
        order_count=len(filtered),
        concentration=resultant,
    )


def build_usual_order_times(
    stamps: list[OrderStamp],
    *,
    now_utc: datetime,
) -> dict[str, dict]:
    """Per-weekday habit map for ``customers.usual_order_times`` JSONB."""
    del now_utc  # stamps already carry age; kept for API symmetry
    out: dict[str, dict] = {}
    weekdays = {s.weekday for s in stamps}
    for wd in sorted(weekdays):
        pred = predict_from_stamps(stamps, weekday=wd, apply_recency=True)
        if pred is None:
            continue
        out[str(wd)] = {
            "minute": pred.minute_of_day,
            "order_count": pred.order_count,
            "concentration": round(pred.concentration, 4),
        }
    return out


def habit_for_weekday(usual_order_times: dict, weekday: int) -> OrderTimePrediction | None:
    """Read a stored weekday habit without hitting the orders table."""
    entry = usual_order_times.get(str(weekday))
    if not entry:
        return None
    return OrderTimePrediction(
        minute_of_day=int(entry["minute"]),
        order_count=int(entry["order_count"]),
        concentration=float(entry["concentration"]),
    )