"""Validated audience-segment DSL.

A segment is a small JSON tree of conditions (spec §4.7) compiled to
SQLAlchemy filters on ``Customer`` — there is **no** ``eval`` and **no** raw
SQL string interpolation anywhere. Every field/op is checked against an
allowlist before a single clause is built; anything unknown raises
``ValueError`` and is never executed.

DSL grammar::

    {"all": [                       # top-level "all" (AND) or "any" (OR)
      {"field": "total_spend",        "op": "gte", "value": 200},
      {"field": "tag",                "op": "contains", "value": "vip"},
      {"field": "order_count",        "op": "gte", "value": 3},
      {"field": "last_order_days_ago","op": "lte", "value": 30},
      {"field": "ordered_dish_id",    "op": "eq",  "value": 1, "min_count": 3}
    ]}
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from app.ordering.models import Customer, Order, OrderItem

# Allowlist: field -> set of permitted ops. Anything outside this table is rejected.
_NUMERIC_OPS = {"eq", "gte", "lte", "gt", "lt"}
_ALLOWED: dict[str, set[str]] = {
    "total_spend": _NUMERIC_OPS,
    "order_count": _NUMERIC_OPS,
    "last_order_days_ago": _NUMERIC_OPS,
    "tag": {"contains"},
    "ordered_dish_id": {"eq"},
}

_NUMERIC_PY_OPS = {
    "eq": lambda col, v: col == v,
    "gte": lambda col, v: col >= v,
    "lte": lambda col, v: col <= v,
    "gt": lambda col, v: col > v,
    "lt": lambda col, v: col < v,
}


def validate_dsl(dsl: Any) -> None:
    """Raise ``ValueError`` on any unknown field/op or malformed structure.

    Must be called before compilation/execution — it is the security gate.
    """
    if not isinstance(dsl, dict):
        raise ValueError("DSL root must be an object")
    keys = set(dsl) & {"all", "any"}
    if len(keys) != 1 or set(dsl) != keys:
        raise ValueError("DSL root must have exactly one of 'all' or 'any'")
    (root,) = keys
    conditions = dsl[root]
    if not isinstance(conditions, list) or not conditions:
        raise ValueError(f"'{root}' must be a non-empty list of conditions")
    for cond in conditions:
        _validate_condition(cond)


def _validate_condition(cond: Any) -> None:
    if not isinstance(cond, dict):
        raise ValueError("each condition must be an object")
    field = cond.get("field")
    op = cond.get("op")
    if field not in _ALLOWED:
        raise ValueError(f"unknown field: {field!r}")
    if op not in _ALLOWED[field]:
        raise ValueError(f"op {op!r} not allowed for field {field!r}")
    if "value" not in cond:
        raise ValueError(f"condition for {field!r} missing 'value'")
    extra = set(cond) - {"field", "op", "value", "min_count"}
    if extra:
        raise ValueError(f"unexpected keys in condition: {sorted(extra)}")
    if field in {"total_spend", "order_count", "last_order_days_ago"}:
        if not isinstance(cond["value"], (int, float)):
            raise ValueError(f"{field!r} value must be numeric")
    if "min_count" in cond:
        if field != "ordered_dish_id":
            raise ValueError("min_count only valid for ordered_dish_id")
        if not isinstance(cond["min_count"], int) or cond["min_count"] < 1:
            raise ValueError("min_count must be a positive integer")


def _build_condition(cond: dict, restaurant_id: int) -> ColumnElement[bool]:
    """Translate one validated condition into a SQLAlchemy boolean clause.

    Aggregates use correlated subqueries / EXISTS against orders/order_items —
    never raw SQL.
    """
    field = cond["field"]
    op = cond["op"]
    value = cond["value"]

    if field == "total_spend":
        return _NUMERIC_PY_OPS[op](Customer.total_spend, value)

    if field == "order_count":
        return _NUMERIC_PY_OPS[op](Customer.total_orders, value)

    if field == "last_order_days_ago":
        cutoff = datetime.now(timezone.utc) - timedelta(days=value)
        # "last_order_days_ago <= N"  ==>  last_order_at >= now-N days.
        recency_ops = {
            "lte": Customer.last_order_at >= cutoff,
            "lt": Customer.last_order_at > cutoff,
            "gte": Customer.last_order_at <= cutoff,
            "gt": Customer.last_order_at < cutoff,
            "eq": func.date(Customer.last_order_at) == func.date(cutoff),
        }
        return and_(Customer.last_order_at.is_not(None), recency_ops[op])

    if field == "tag":
        # tags is a JSONB dict whose keys are tag labels — membership = has_key.
        return Customer.tags.has_key(value)  # noqa: W601 (SQLAlchemy JSONB op)

    if field == "ordered_dish_id":
        min_count = cond.get("min_count", 1)
        qty_total = (
            select(func.coalesce(func.sum(OrderItem.qty), 0))
            .select_from(OrderItem)
            .join(Order, Order.id == OrderItem.order_id)
            .where(
                Order.customer_id == Customer.id,
                Order.restaurant_id == restaurant_id,
                OrderItem.dish_id == value,
            )
            .correlate(Customer)
            .scalar_subquery()
        )
        return qty_total >= min_count

    raise ValueError(f"unhandled field: {field!r}")  # pragma: no cover (validate gates this)


def compile_segment(dsl: dict, restaurant_id: int):
    """Compile a *validated* DSL into ``select(Customer.id)`` scoped to a tenant.

    Caller must have run :func:`validate_dsl` (``evaluate_segment`` does).
    """
    (root,) = set(dsl) & {"all", "any"}
    clauses = [_build_condition(c, restaurant_id) for c in dsl[root]]
    combined = and_(*clauses) if root == "all" else or_(*clauses)
    return (
        select(Customer.id)
        .where(Customer.restaurant_id == restaurant_id)
        .where(combined)
    )


async def evaluate_segment(session, *, restaurant_id: int, dsl: dict) -> list[int]:
    """Validate, compile, and run the segment scoped to ``restaurant_id``.

    Returns the list of matching ``customer_id``s.
    """
    validate_dsl(dsl)
    stmt = compile_segment(dsl, restaurant_id)
    rows = await session.execute(stmt)
    return [r[0] for r in rows.all()]


async def preview_count(session, *, restaurant_id: int, dsl: dict) -> int:
    """Count matching customers without materialising the id list."""
    validate_dsl(dsl)
    inner = compile_segment(dsl, restaurant_id).subquery()
    stmt = select(func.count()).select_from(inner)
    return int((await session.execute(stmt)).scalar_one())
