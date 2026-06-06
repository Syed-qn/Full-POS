"""Predictions service — where the forecast model meets the DB (spec §4.6).

Responsibilities (Task 7 of the Phase-6 plan):
  * ``run_forecast``     — pull trailing order history, fit the model, project the
                           horizon window into a ``PredictionRun`` (+ ModelRegistry),
                           apply any active ``ManagerOverride``s, ``record_audit``.
  * ``prep_ahead_suggestions`` — top-K dishes a manager should prep ahead.
  * ``create_override``  — parse a manager's plain-English note → DSL → persist.
  * ``latest_run`` / ``list_runs`` — tenant-scoped read helpers.

Conventions: every query is scoped by ``restaurant_id`` (multi-tenancy); money is
``Decimal`` / ``Numeric(8,2)`` AED; the caller owns the transaction commit
(services flush, never commit — mirrors audit/outbox). Routers never touch other
modules' models — they call this service, which reaches into menu/ordering.
"""

from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from math import ceil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.llm.port import ForecastAdjusterPort
from app.menu.models import Dish
from app.ordering.models import Order, OrderItem
from app.predictions.adjust import apply_overrides
from app.predictions.features import build_observations
from app.predictions.models import ManagerOverride, ModelRegistry, PredictionRun
from app.predictions.port import ForecastModel

# Statuses that count as "real demand" history (order placed and not cancelled).
_DEMAND_STATUSES = ("confirmed", "ready", "assigned", "out_for_delivery", "delivered")

# Horizon -> clock hours covered. ``next_1h`` resolves dynamically at call time.
_HORIZON_HOURS: dict[str, list[int]] = {
    "breakfast": [6, 7, 8, 9, 10],
    "lunch": [11, 12, 13, 14, 15],
    "dinner": [18, 19, 20, 21, 22],
    "midnight": [23, 0, 1, 2],
}

_TRAILING_DAYS = 28
_VALID_OVERRIDE_KEYS = {
    "horizon",
    "dow",
    "order_count_delta",
    "order_count_mult",
    "revenue_mult",
    "dish_demand_delta",
}


def _horizon_hours(horizon: str) -> list[int]:
    if horizon == "next_1h":
        return [(datetime.now().hour + 1) % 24]
    hours = _HORIZON_HOURS.get(horizon)
    if hours is None:
        raise ValueError(f"Unknown horizon: {horizon!r}")
    return hours


async def run_forecast(
    session: AsyncSession,
    *,
    restaurant_id: int,
    target_date: date,
    horizon: str,
    model: ForecastModel,
) -> PredictionRun:
    """Forecast the ``horizon`` window of ``target_date`` and persist a run.

    Pulls the trailing ``_TRAILING_DAYS`` of demand-bearing order items, fits the
    model, sums ``predict_dish_hour`` across active dishes over the horizon hours,
    applies active manager overrides, and writes a ``PredictionRun`` (+ upserts a
    ``ModelRegistry`` row). The caller commits.
    """
    hours = _horizon_hours(horizon)
    dow = target_date.weekday()

    window_start = datetime.combine(target_date - timedelta(days=_TRAILING_DAYS), time.min)

    # Trailing order items for this tenant (snapshot price lives on the item row).
    item_rows = (
        await session.execute(
            select(
                OrderItem.dish_id,
                OrderItem.qty,
                Order.created_at,
            )
            .join(Order, OrderItem.order_id == Order.id)
            .where(
                Order.restaurant_id == restaurant_id,
                Order.status.in_(_DEMAND_STATUSES),
                Order.created_at >= window_start,
            )
        )
    ).all()

    observations = build_observations(
        [
            {"dish_id": r.dish_id, "qty": r.qty, "ordered_at": r.created_at}
            for r in item_rows
        ]
    )
    model.fit(observations)

    # Mean trailing delivery distance (NULL distances skipped).
    distances = [
        r.distance_km
        for r in (
            await session.execute(
                select(Order.distance_km).where(
                    Order.restaurant_id == restaurant_id,
                    Order.status.in_(_DEMAND_STATUSES),
                    Order.created_at >= window_start,
                    Order.distance_km.isnot(None),
                )
            )
        ).all()
    ]
    avg_distance_km = round(sum(distances) / len(distances), 2) if distances else None

    # Active dishes with prices for this tenant.
    dishes = (
        await session.execute(
            select(Dish).where(
                Dish.restaurant_id == restaurant_id,
                Dish.is_available.is_(True),
            )
        )
    ).scalars().all()

    dish_demand: dict[str, float] = {}
    order_count_raw = 0.0
    revenue = Decimal("0.00")
    for dish in dishes:
        expected = 0.0
        for hour in hours:
            forecast = model.predict_dish_hour(dish_id=dish.id, dow=dow, hour=hour)
            expected += forecast.expected_qty
        if expected <= 0:
            continue
        dish_demand[str(dish.id)] = round(expected, 2)
        order_count_raw += expected
        price = dish.price_aed or Decimal("0.00")
        revenue += (Decimal(str(expected)) * price).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    predicted: dict = {
        "order_count": int(round(order_count_raw)),
        "revenue": str(revenue),
        "dish_demand": dish_demand,
        "avg_distance_km": avg_distance_km,
    }

    # --- active manager overrides covering this target_date + horizon/dow ---
    target_dt = datetime.combine(target_date, time.min)
    override_rows = (
        await session.execute(
            select(ManagerOverride).where(
                ManagerOverride.restaurant_id == restaurant_id,
                ManagerOverride.enabled.is_(True),
                ManagerOverride.active_from <= target_dt,
                ManagerOverride.active_to > target_dt,
            )
        )
    ).scalars().all()

    effects = [
        ov.parsed_effect
        for ov in override_rows
        if _override_matches(ov.parsed_effect, horizon=horizon, dow=dow)
    ]
    adjusted_predicted, reasoning = apply_overrides(predicted, effects)
    adjusted = bool(effects) and bool(reasoning)

    run = PredictionRun(
        restaurant_id=restaurant_id,
        horizon=horizon,
        target_date=target_date,
        predicted=adjusted_predicted,
        model_version=_model_version(model),
        adjusted=adjusted,
        reasoning=reasoning or None,
    )
    session.add(run)
    await session.flush()

    if adjusted:
        for ov in override_rows:
            ov.applied_to_runs = [*(ov.applied_to_runs or []), run.id]

    await _upsert_model_registry(
        session,
        restaurant_id=restaurant_id,
        version=run.model_version,
        n_samples=len(observations),
    )

    await record_audit(
        session,
        actor="system",
        restaurant_id=restaurant_id,
        entity="prediction_run",
        entity_id=str(run.id),
        action="forecast",
        after={
            "horizon": horizon,
            "target_date": target_date.isoformat(),
            "order_count": adjusted_predicted["order_count"],
            "adjusted": adjusted,
        },
    )
    return run


def _model_version(model: ForecastModel) -> str:
    """Resolve a model's version string (Protocol has no required attribute)."""
    version = getattr(model, "model_version", None)
    if version:
        return str(version)
    # Models that expose version only via a per-dish forecast (e.g. FakeForecastModel).
    return model.predict_dish_hour(dish_id=0, dow=0, hour=0).model_version


def _override_matches(effect: dict, *, horizon: str, dow: int) -> bool:
    """An override applies when its (optional) horizon/dow advisory keys match."""
    if effect.get("horizon") not in (None, horizon):
        return False
    if effect.get("dow") not in (None, dow):
        return False
    return True


async def _upsert_model_registry(
    session: AsyncSession,
    *,
    restaurant_id: int,
    version: str,
    n_samples: int,
) -> ModelRegistry:
    model_type = version.split("-", 1)[0]
    existing = (
        await session.execute(
            select(ModelRegistry).where(
                ModelRegistry.restaurant_id == restaurant_id,
                ModelRegistry.version == version,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.metrics = {**(existing.metrics or {}), "n_samples": n_samples}
        return existing
    row = ModelRegistry(
        restaurant_id=restaurant_id,
        model_type=model_type,
        version=version,
        metrics={"n_samples": n_samples},
    )
    session.add(row)
    return row


async def prep_ahead_suggestions(
    session: AsyncSession,
    *,
    restaurant_id: int,
    run: PredictionRun,
    top_k: int = 5,
    min_qty: float = 3.0,
) -> list[dict]:
    """Top-K dishes (expected qty >= ``min_qty``) to prep ahead. Pure read.

    Each item: ``{dish_id, dish_name, expected_qty, suggested_prep}`` where
    ``suggested_prep = ceil(expected_qty)``.
    """
    demand: dict = run.predicted.get("dish_demand", {})
    ranked = sorted(
        ((int(dish_id), float(qty)) for dish_id, qty in demand.items() if float(qty) >= min_qty),
        key=lambda pair: pair[1],
        reverse=True,
    )[:top_k]
    if not ranked:
        return []

    dish_ids = [dish_id for dish_id, _ in ranked]
    name_by_id = dict(
        (
            await session.execute(
                select(Dish.id, Dish.name).where(
                    Dish.restaurant_id == restaurant_id,
                    Dish.id.in_(dish_ids),
                )
            )
        ).all()
    )
    return [
        {
            "dish_id": dish_id,
            "dish_name": name_by_id.get(dish_id, f"dish-{dish_id}"),
            "expected_qty": qty,
            "suggested_prep": ceil(qty),
        }
        for dish_id, qty in ranked
    ]


async def create_override(
    session: AsyncSession,
    *,
    restaurant_id: int,
    text: str,
    adjuster: ForecastAdjusterPort,
    active_from: datetime,
    active_to: datetime,
) -> ManagerOverride:
    """Parse a manager's plain-English override → DSL → persist. Caller commits."""
    parsed = adjuster.parse_override(text)
    effect = {k: v for k, v in parsed.items() if k in _VALID_OVERRIDE_KEYS}

    row = ManagerOverride(
        restaurant_id=restaurant_id,
        text=text,
        parsed_effect=effect,
        active_from=active_from,
        active_to=active_to,
    )
    session.add(row)
    await session.flush()

    await record_audit(
        session,
        actor="manager",
        restaurant_id=restaurant_id,
        entity="manager_override",
        entity_id=str(row.id),
        action="create",
        after={"text": text, "parsed_effect": effect},
    )
    return row


async def latest_run(
    session: AsyncSession,
    *,
    restaurant_id: int,
    horizon: str | None = None,
) -> PredictionRun | None:
    """Most recent run for a tenant (optionally a single horizon)."""
    stmt = (
        select(PredictionRun)
        .where(PredictionRun.restaurant_id == restaurant_id)
        .order_by(PredictionRun.target_date.desc(), PredictionRun.created_at.desc())
        .limit(1)
    )
    if horizon is not None:
        stmt = stmt.where(PredictionRun.horizon == horizon)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_runs(
    session: AsyncSession,
    *,
    restaurant_id: int,
    limit: int = 20,
) -> list[PredictionRun]:
    """Tenant-scoped runs, newest target_date first."""
    stmt = (
        select(PredictionRun)
        .where(PredictionRun.restaurant_id == restaurant_id)
        .order_by(PredictionRun.target_date.desc(), PredictionRun.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())
