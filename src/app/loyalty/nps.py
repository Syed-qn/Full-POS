"""Net Promoter Score survey — a NEW, non-overlapping addition to the
tier/earn loyalty system in :mod:`app.loyalty.service`.

One :class:`NpsResponse` per (customer, order) survey answer. ``nps_summary``
computes the textbook NPS formula: (promoters − detractors) / total * 100.
"""
from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.service import record_audit
from app.loyalty.models import NpsResponse

_PROMOTER_MIN = 9
_DETRACTOR_MAX = 6


async def record_nps_response(
    session: AsyncSession, *, restaurant_id: int, customer_id: int, order_id: int,
    score: int, comment: str | None,
) -> NpsResponse:
    """Record one NPS response. Raises ``ValueError`` if score is not 0-10.
    Caller commits."""
    if not isinstance(score, int) or not (0 <= score <= 10):
        raise ValueError(f"NPS score must be an integer 0-10, got {score!r}")
    row = NpsResponse(
        restaurant_id=restaurant_id, customer_id=customer_id, order_id=order_id,
        score=score, comment=comment,
    )
    session.add(row)
    await session.flush()
    await record_audit(
        session, actor="customer", restaurant_id=restaurant_id,
        entity="nps_response", entity_id=str(row.id), action="recorded",
        before=None, after={"order_id": order_id, "score": score},
    )
    return row


def _day_bounds_utc(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    """Naive UTC bounds — ``created_at`` is stored as a naive UTC timestamp
    (TimestampMixin has no ``timezone=True``), so comparisons must be naive too."""
    start = datetime.combine(start_date, time.min)
    end = datetime.combine(end_date, time.max)
    return start, end


async def nps_summary(
    session: AsyncSession, *, restaurant_id: int, start_date: date, end_date: date
) -> dict:
    """Promoters (9-10) minus detractors (0-6), as a percentage of total
    responses in [start_date, end_date] inclusive (UTC day bounds)."""
    start, end = _day_bounds_utc(start_date, end_date)
    promoters = await session.scalar(
        select(func.count(NpsResponse.id)).where(
            NpsResponse.restaurant_id == restaurant_id,
            NpsResponse.created_at >= start, NpsResponse.created_at <= end,
            NpsResponse.score >= _PROMOTER_MIN,
        )
    )
    detractors = await session.scalar(
        select(func.count(NpsResponse.id)).where(
            NpsResponse.restaurant_id == restaurant_id,
            NpsResponse.created_at >= start, NpsResponse.created_at <= end,
            NpsResponse.score <= _DETRACTOR_MAX,
        )
    )
    total = await session.scalar(
        select(func.count(NpsResponse.id)).where(
            NpsResponse.restaurant_id == restaurant_id,
            NpsResponse.created_at >= start, NpsResponse.created_at <= end,
        )
    )
    promoters = int(promoters or 0)
    detractors = int(detractors or 0)
    total = int(total or 0)
    passives = total - promoters - detractors
    nps_score = round((promoters - detractors) / total * 100, 2) if total else 0.0
    return {
        "nps_score": nps_score,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "total_responses": total,
    }
