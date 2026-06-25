"""Named audience segments (RFM-style) over ``Customer``.

A provisional, industry-standard-ish split on **Recency** (days since last order)
and **Frequency** (lifetime order count). Buckets are **mutually exclusive** —
every customer falls into exactly one, so the per-bucket counts sum to the total
("All Customers"). This mirrors how RFM dashboards present non-overlapping cohorts.

``_classify`` is the SINGLE source of truth for the formula: tune it (or swap in
monetary scoring on ``total_spend``) without touching the counts/targeting code
or the API. Everything else just calls it.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ordering.models import Customer

# Display order for the pills. "all" is the whole opted-in base (no formula).
RFM_SEGMENTS: list[tuple[str, str]] = [
    ("champions", "Champions"),
    ("loyal", "Loyal Customers"),
    ("potential", "Potential Loyalists"),
    ("at_risk", "At Risk"),
    ("lost", "Lost"),
    ("new", "New Customers"),
    ("all", "All Customers"),
]
VALID_KEYS = {key for key, _ in RFM_SEGMENTS}


def _classify(*, total_orders: int, last_order_at: datetime | None, now: datetime) -> str:
    """Assign one customer to exactly one named bucket. Order = priority.

    Recency (R) is days since the last order; Frequency (F) is the lifetime
    order count. Change these thresholds to retune the cohorts.
    """
    f = total_orders or 0
    # Brand-new / single-order customers, regardless of recency.
    if f <= 1:
        return "new"
    # Never ordered (no recency signal) but somehow F>1 — treat as lost.
    if last_order_at is None:
        return "lost"
    r = (now - last_order_at).days
    if f >= 5 and r <= 30:
        return "champions"
    if f >= 3 and r <= 60:
        return "loyal"
    if r <= 30:
        return "potential"      # repeat buyer, recent, not yet frequent
    if r <= 120:
        return "at_risk"        # was a repeat buyer, going quiet
    return "lost"               # long lapsed


async def _rows(session: AsyncSession, restaurant_id: int) -> list[tuple[int, int, datetime | None]]:
    res = await session.execute(
        select(Customer.id, Customer.total_orders, Customer.last_order_at).where(
            Customer.restaurant_id == restaurant_id
        )
    )
    return list(res.all())


async def segment_counts(
    session: AsyncSession, *, restaurant_id: int, now: datetime | None = None
) -> dict[str, int]:
    """Count customers per bucket (mutually exclusive) plus ``all`` = total."""
    now = now or datetime.now(timezone.utc)
    counts = {key: 0 for key, _ in RFM_SEGMENTS}
    rows = await _rows(session, restaurant_id)
    for _id, total_orders, last_order_at in rows:
        counts[_classify(total_orders=total_orders, last_order_at=last_order_at, now=now)] += 1
    counts["all"] = len(rows)
    return counts


async def segment_customer_ids(
    session: AsyncSession, *, restaurant_id: int, key: str, now: datetime | None = None
) -> list[int]:
    """Customer ids in one bucket. ``all`` returns every customer of the tenant."""
    if key not in VALID_KEYS:
        raise ValueError(f"unknown segment: {key!r}")
    now = now or datetime.now(timezone.utc)
    rows = await _rows(session, restaurant_id)
    if key == "all":
        return [r[0] for r in rows]
    return [
        r[0]
        for r in rows
        if _classify(total_orders=r[1], last_order_at=r[2], now=now) == key
    ]
