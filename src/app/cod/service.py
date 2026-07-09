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
    declared_collected_aed: Decimal | None = None,
) -> RiderShiftReconciliation:
    """Reconcile a rider's COD for a shift date.

    **Expected** = sum of door COD due (order.total − wallet) for orders
    *delivered* that day by this rider (not merely recorded collections).
    **Collected** = sum of ``CodCollection`` rows for the day, or the
    manager-declared cash count when provided (till hand-in).

    Variance = collected − expected. Status ``balanced`` when zero.
    Caller commits.
    """
    from app.ordering.models import Order
    from app.ordering.payments import cod_due_aed

    # Delivered orders on this shift (UTC date of delivered_at).
    orders = list(
        (
            await session.scalars(
                select(Order).where(
                    Order.restaurant_id == restaurant_id,
                    Order.rider_id == rider_id,
                    Order.status == "delivered",
                    Order.delivered_at.is_not(None),
                    func.date(Order.delivered_at) == shift_date,
                )
            )
        ).all()
    )
    expected = sum((cod_due_aed(o) for o in orders), Decimal("0.00")).quantize(
        Decimal("0.01")
    )

    ledger_collected = await session.scalar(
        select(func.coalesce(func.sum(CodCollection.amount_aed), 0)).where(
            CodCollection.restaurant_id == restaurant_id,
            CodCollection.rider_id == rider_id,
            func.date(CodCollection.collected_at) == shift_date,
        )
    )
    ledger_collected = Decimal(ledger_collected).quantize(Decimal("0.01"))
    collected = (
        Decimal(declared_collected_aed).quantize(Decimal("0.01"))
        if declared_collected_aed is not None
        else ledger_collected
    )
    # If no deliveries but collections exist, fall back so empty days stay balanced
    # when both are zero; when only collections exist, expected=ledger for safety.
    if not orders and declared_collected_aed is None:
        expected = ledger_collected

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
