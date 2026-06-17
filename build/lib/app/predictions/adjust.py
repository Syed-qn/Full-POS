"""Deterministic manager-override adjustment layer (spec §4.6).

``apply_overrides`` merges any active ``ManagerOverride.parsed_effect`` DSL dicts
into a predicted forecast dict. Pure & side-effect free: the input ``predicted``
is never mutated. Deltas are applied first, then multipliers — so a row carrying
both ``order_count_delta`` and ``order_count_mult`` scales the post-delta value.

parsed_effect DSL (all keys optional)::

    {
        "horizon": "lunch" | null,            # advisory only at apply time
        "dow": 0-6 | null,                     # advisory only at apply time
        "order_count_delta": int,              # default 0
        "order_count_mult": float,             # default 1.0
        "revenue_mult": float,                 # default 1.0
        "dish_demand_delta": {dish_id: int},   # merged per dish_id
    }
"""

from copy import deepcopy
from decimal import ROUND_HALF_UP, Decimal


def _money(value) -> Decimal:
    return Decimal(str(value))


def apply_overrides(predicted: dict, effects: list[dict]) -> tuple[dict, str]:
    """Apply ``effects`` to a copy of ``predicted``.

    Returns ``(adjusted_dict, reasoning)``. ``reasoning`` is a human-readable
    summary of applied effects, or ``""`` when ``effects`` is empty.
    """
    if not effects:
        return predicted, ""

    out = deepcopy(predicted)
    notes: list[str] = []

    for effect in effects:
        # --- deltas first ---
        count_delta = int(effect.get("order_count_delta", 0) or 0)
        if count_delta and "order_count" in out:
            out["order_count"] = int(out["order_count"]) + count_delta
            notes.append(f"order_count {count_delta:+d}")

        dish_delta = effect.get("dish_demand_delta") or {}
        if dish_delta:
            demand = out.setdefault("dish_demand", {})
            for dish_id, delta in dish_delta.items():
                key = str(dish_id)
                demand[key] = int(demand.get(key, 0)) + int(delta)
            notes.append(
                "dish_demand "
                + ", ".join(f"{k}{int(v):+d}" for k, v in dish_delta.items())
            )

        # --- multipliers second ---
        count_mult = float(effect.get("order_count_mult", 1.0) or 1.0)
        if count_mult != 1.0 and "order_count" in out:
            out["order_count"] = int(
                (Decimal(str(out["order_count"])) * _money(count_mult)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
            notes.append(f"order_count x{count_mult:g}")

        revenue_mult = float(effect.get("revenue_mult", 1.0) or 1.0)
        if revenue_mult != 1.0 and "revenue" in out:
            out["revenue"] = str(
                (_money(out["revenue"]) * _money(revenue_mult)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )
            notes.append(f"revenue x{revenue_mult:g}")

    reasoning = "Applied manager override(s): " + "; ".join(notes) if notes else ""
    return out, reasoning
