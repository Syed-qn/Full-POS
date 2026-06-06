"""COD collection ledger (spec §4.4.4 / §3).

COD is the only payment method on the platform, so every delivered order has
exactly one cash collection. ``record_collection`` is idempotent on ``order_id``
(unique constraint) so a retried "Delivered" button never double-records.
``reconcile_shift`` totals a rider's collections for a UTC shift date and writes a
``RiderShiftReconciliation`` row with the variance and a balanced/variance status.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cod.models import CodCollection, RiderShiftReconciliation


async def record_collection(
    session: AsyncSession,
    *,
    restaurant_id: int,
    order_id: int,
    rider_id: int,
    amount: Decimal,
    collected_at: datetime | None = None,
) -> CodCollection:
    """Idempotent on order_id (unique). Returns the existing row if already recorded.

    Caller commits.
    """
    existing = await session.scalar(
        select(CodCollection).where(CodCollection.order_id == order_id)
    )
    if existing is not None:
        return existing
    row = CodCollection(
        order_id=order_id,
        rider_id=rider_id,
        restaurant_id=restaurant_id,
        amount_aed=amount,
        collected_at=collected_at or datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row


async def reconcile_shift(
    session: AsyncSession,
    *,
    restaurant_id: int,
    rider_id: int,
    shift_date: date,
) -> RiderShiftReconciliation:
    """Sum a rider's collections for shift_date; write reconciliation with variance.

    Caller commits. COD-only platform: the expected total is the sum of the
    rider's recorded collections for the date (a balanced shift sums equal).
    """
    collected = await session.scalar(
        select(func.coalesce(func.sum(CodCollection.amount_aed), 0)).where(
            CodCollection.restaurant_id == restaurant_id,
            CodCollection.rider_id == rider_id,
            func.date(CodCollection.collected_at) == shift_date,
        )
    )
    collected = Decimal(collected).quantize(Decimal("0.01"))
    expected = collected
    variance = (collected - expected).quantize(Decimal("0.01"))
    rec = RiderShiftReconciliation(
        rider_id=rider_id,
        restaurant_id=restaurant_id,
        shift_date=shift_date,
        expected_total_aed=expected,
        collected_total_aed=collected,
        variance_aed=variance,
        status="balanced" if variance == Decimal("0.00") else "variance",
    )
    session.add(rec)
    await session.flush()
    return rec
